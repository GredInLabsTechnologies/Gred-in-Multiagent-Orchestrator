"""GIMO Core entrypoint under Chaquopy (Fase B).

Chaquopy embeds a bionic-compatible CPython 3.13 into the APK and exposes
`Python.getInstance()` to Kotlin. Because there is no subprocess boundary
(Chaquopy uses a singleton interpreter per JVM process), the entrypoint
runs uvicorn on a daemon thread inside the same JVM and exposes cheap
callables for `start_server` / `stop_server` / `is_running`.

Runtime layout (set up by EmbeddedCoreRunner.kt via Kotlin):
  - Chaquopy provides: CPython 3.13 + pure-Python wheels (fastapi, uvicorn,
    starlette, typing-extensions, h11, anyio, sniffio, idna, click,
    python-multipart) under `chaquopy/lib-packages/`.
  - Rove bundle provides, extracted to `filesDir/runtime/extracted/`:
      site-packages/   — bionic wheels (pydantic_core, cryptography, psutil,
                         orjson, ...) cross-compiled by the rove pipeline.
      repo/tools/      — the GIMO Core source tree.
  - `start_server(args)` receives both the rove paths and the canonical
    ORCH_* env vars from Kotlin; it wires them into `sys.path` / `os.environ`
    before importing anything from `tools.gimo_server`.

Lifecycle contract (called from ChaquopyBridge / EmbeddedCoreRunner):
  start_server(args)        -> None   (idempotent; noop if already running)
  stop_server()             -> None   (signals uvicorn to exit)
  is_running()              -> bool
  wait_for_shutdown(timeout)-> bool   (True if shut down cleanly)

All top-level work that talks to the network is deferred to the background
thread so Python startup in onCreate stays < 100 ms.
"""
from __future__ import annotations

import logging
import os
import sys
import threading
from typing import Any, Dict, Optional

logger = logging.getLogger("gimo.chaquopy.entry")

_server: Optional["uvicorn.Server"] = None  # type: ignore[name-defined]
_thread: Optional[threading.Thread] = None
_stop_event = threading.Event()
_lock = threading.RLock()


def _coerce_java_map(m: Any) -> Dict[str, Any]:
    """Convert a Chaquopy-proxied java.util.Map into a real Python dict.

    Chaquopy wraps Kotlin Map<String, Any> as java.util.LinkedHashMap which
    is neither iterable nor does it expose `.items()` / two-arg `.get()`.
    We iterate keySet() (always present on java.util.Map) and fetch each
    value via bracket syntax (proxies to Map.get(key)). Nested Kotlin Maps
    (e.g. the `env` sub-map) are coerced recursively.
    """
    if m is None:
        return {}
    if isinstance(m, dict):
        return m
    out: Dict[str, Any] = {}
    try:
        # Java Map's keySet() returns a view that Chaquopy proxies without a
        # Python iterator protocol. toArray() returns a Java Object[] which
        # IS iterable via Chaquopy's array adapter.
        if hasattr(m, "keySet"):
            keys = list(m.keySet().toArray())
        else:
            keys = list(m.keys())
        for k in keys:
            key = str(k)
            value = m[k]
            if value is not None and hasattr(value, "keySet"):
                value = _coerce_java_map(value)
            out[key] = value
    except Exception as exc:  # pragma: no cover — belt-and-braces
        logger.exception("java map coercion failed: %s", exc)
    return out


def _prepend_sys_path(entries: list[str]) -> None:
    """Insert each entry at sys.path[0], preserving relative order."""
    for entry in reversed(entries):
        if not entry:
            continue
        if entry in sys.path:
            sys.path.remove(entry)
        sys.path.insert(0, entry)


def _unpack_wheelhouse(wheelhouse_dir: str, dest_site_packages: str) -> str:
    """Extract every .whl in wheelhouse_dir into dest_site_packages (idempotent).

    Needed because the rove bundle ships wheels that pip already resolved and
    cross-compiled for bionic aarch64, but Python can't import directly from a
    .whl on sys.path — it expects unpacked packages. On first boot we unpack
    once; subsequent boots see the marker file and skip.

    Returns the dest_site_packages path (or empty string on failure).
    """
    import glob
    import os
    import zipfile

    marker = os.path.join(dest_site_packages, ".unpacked.ok")
    if os.path.exists(marker):
        return dest_site_packages

    try:
        os.makedirs(dest_site_packages, exist_ok=True)
        wheels = sorted(glob.glob(os.path.join(wheelhouse_dir, "*.whl")))
        for whl in wheels:
            with zipfile.ZipFile(whl) as zf:
                zf.extractall(dest_site_packages)
        with open(marker, "w") as f:
            f.write("ok\n")
        logger.info("unpacked %d wheels into %s", len(wheels), dest_site_packages)
        return dest_site_packages
    except Exception as exc:
        logger.exception("wheelhouse unpack failed: %s", exc)
        return ""


def start_server(args: Dict[str, Any]) -> None:
    """Start uvicorn in a daemon thread. Idempotent.

    Expected keys in ``args`` (all str unless noted):
      rove_site_packages:   absolute path to extracted/site-packages/.
      rove_repo_root:       absolute path to extracted/repo/ (contains tools/).
      rove_extra_paths:     ':'-joined extra sys.path entries (optional).
      env:                  dict[str, str] of ORCH_* env vars to publish.
      host:                 bind host, usually "0.0.0.0".
      port:                 bind port, int.
    """
    global _server, _thread
    # Chaquopy proxies the Kotlin Map as java.util.LinkedHashMap whose `.get`
    # takes only 1 argument — Python's `dict.get(key, default)` doesn't map.
    # Coerce to a real Python dict up front so the rest of the code can use
    # Pythonic APIs.
    args = _coerce_java_map(args)
    with _lock:
        if _thread is not None and _thread.is_alive():
            logger.info("start_server: already running")
            return
        _stop_event.clear()

        # 1. Path layering. rove site-packages / unpacked wheelhouse first so
        #    pydantic_core (Rust) and cryptography win over anything Chaquopy
        #    installed.
        extra = args.get("rove_extra_paths", "")
        path_entries: list[str] = []

        # 1a. Unpack the rove wheelhouse on first boot so Python can import
        #     from a real site-packages tree (wheels on sys.path alone don't
        #     work — Python wants unpacked packages).
        wheelhouse = args.get("rove_wheelhouse_dir", "")
        wheelhouse_target = args.get("rove_wheelhouse_target", "")
        if wheelhouse and wheelhouse_target:
            unpacked = _unpack_wheelhouse(wheelhouse, wheelhouse_target)
            if unpacked:
                path_entries.append(unpacked)

        site_pkgs = args.get("rove_site_packages", "")
        if site_pkgs:
            path_entries.append(site_pkgs)
        if extra:
            path_entries.extend(e for e in extra.split(os.pathsep) if e)
        repo_root = args.get("rove_repo_root", "")
        if repo_root:
            path_entries.append(repo_root)
        _prepend_sys_path(path_entries)

        # 2. Environment variables — merge, don't replace. Android already
        #    has HOME/TMPDIR set by Chaquopy; we just add ORCH_*.
        env = args.get("env") or {}
        for k, v in env.items():
            if isinstance(v, str):
                os.environ[k] = v

        host = str(args.get("host", "0.0.0.0"))
        port = int(args.get("port", 9325))

        def _run() -> None:
            global _server
            try:
                # Late imports — only now sys.path has the rove layers.
                import uvicorn  # noqa: F401
                from tools.gimo_server.main import app  # type: ignore[import]

                config = uvicorn.Config(  # type: ignore[attr-defined]
                    app=app,
                    host=host,
                    port=port,
                    log_level="info",
                    loop="asyncio",
                    lifespan="on",
                    # Stay explicit about the event-loop policy. Uvicorn would
                    # otherwise try to auto-detect uvloop which we excluded
                    # (no bionic wheel). Asyncio is correct for our latency
                    # envelope.
                )
                _server = uvicorn.Server(config)  # type: ignore[attr-defined]
                _server.run()
            except BaseException as exc:
                logger.exception("uvicorn run failed: %s", exc)
            finally:
                _stop_event.set()

        _thread = threading.Thread(
            target=_run, name="gimo-uvicorn", daemon=True,
        )
        _thread.start()
        logger.info("start_server: thread spawned (host=%s port=%d)", host, port)


def stop_server() -> None:
    """Signal uvicorn to shut down. Non-blocking."""
    global _server
    with _lock:
        if _server is not None:
            try:
                _server.should_exit = True
            except Exception as exc:  # pragma: no cover
                logger.warning("stop_server: setting should_exit failed: %s", exc)


def wait_for_shutdown(timeout_seconds: float = 10.0) -> bool:
    """Block until the uvicorn thread exits or timeout elapses."""
    return _stop_event.wait(timeout_seconds)


def is_running() -> bool:
    with _lock:
        return _thread is not None and _thread.is_alive() and not _stop_event.is_set()


def runtime_probe(args: Dict[str, Any]) -> Dict[str, str]:
    """Verify that sys.path layering imports the real GIMO Core.

    Does NOT start the server — callable from Kotlin as a cheap pre-flight
    check. Returns a dict with the resolved versions of the canonical deps
    so the Android side can show "fastapi=X.Y / pydantic=X.Y.Z" in the UI.
    Any import failure returns an explicit {"ok": "false", "error": str}.
    """
    args = _coerce_java_map(args)
    try:
        path_entries: list[str] = []
        site_pkgs = args.get("rove_site_packages", "")
        if site_pkgs:
            path_entries.append(site_pkgs)
        extra = args.get("rove_extra_paths", "")
        if extra:
            path_entries.extend(e for e in extra.split(os.pathsep) if e)
        repo_root = args.get("rove_repo_root", "")
        if repo_root:
            path_entries.append(repo_root)
        _prepend_sys_path(path_entries)

        import fastapi  # noqa: F401
        import uvicorn  # noqa: F401
        import pydantic  # noqa: F401
        try:
            import tools.gimo_server  # type: ignore[import]  # noqa: F401
            core_ok = "true"
        except Exception as exc:  # pragma: no cover
            core_ok = f"false:{exc!r}"

        return {
            "ok": "true",
            "fastapi": getattr(fastapi, "__version__", "?"),
            "uvicorn": getattr(uvicorn, "__version__", "?"),
            "pydantic": getattr(pydantic, "VERSION", getattr(pydantic, "__version__", "?")),
            "core_import": core_ok,
        }
    except Exception as exc:
        return {"ok": "false", "error": repr(exc)}
