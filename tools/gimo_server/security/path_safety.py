"""Path traversal guard for user-controlled path fragments (CWE-22/23).

SonarCloud rules: pythonsecurity:S2083 and pythonsecurity:S6549.

This module is the single source of truth for user-path → base-dir resolution.
Callers should prefer :func:`safe_join` (strict, raises) for service code and
:func:`normalize_under_base` (lenient, returns ``None`` on failure) for HTTP
handlers that want to produce a friendlier response.

Legacy wrapper: :func:`tools.gimo_server.security.validation.validate_path` now
delegates here — do not reintroduce the normalization logic elsewhere.
"""
from __future__ import annotations

import re
from pathlib import Path
from typing import Optional, Union


PathLike = Union[str, Path]


class PathTraversalError(ValueError):
    """Raised when a user-supplied path tries to escape its base directory."""


# Windows reserved device names. Match is case-insensitive and applies to each
# path component's basename (pre-extension), e.g. ``CON.txt`` is rejected.
_WINDOWS_RESERVED = frozenset(
    {
        "CON", "PRN", "AUX", "NUL",
        "COM1", "COM2", "COM3", "COM4", "COM5", "COM6", "COM7", "COM8", "COM9",
        "LPT1", "LPT2", "LPT3", "LPT4", "LPT5", "LPT6", "LPT7", "LPT8", "LPT9",
    }
)

_COMPONENT_SPLIT = re.compile(r"[\\/]")


def _reject_unsafe_components(path_str: str) -> None:
    """Raise :class:`PathTraversalError` if the string has forbidden components.

    Checks performed:

    - null bytes (classic filesystem injection vector)
    - Windows reserved device names on any component
    """
    if "\0" in path_str:
        raise PathTraversalError("Null byte in path")

    for component in _COMPONENT_SPLIT.split(path_str):
        if not component:
            continue
        base_name = component.split(".")[0].upper()
        if base_name in _WINDOWS_RESERVED:
            raise PathTraversalError(f"Reserved device name: {component!r}")


def safe_join(base: PathLike, user_path: PathLike) -> Path:
    """Join ``user_path`` under ``base`` ensuring the result stays inside.

    - Resolves both sides to absolute, symlink-resolved paths.
    - Rejects null bytes and Windows reserved device names.
    - Rejects absolute ``user_path`` values (they would override ``base``).
    - Raises :class:`PathTraversalError` if the final path is not a descendant
      of ``base``.
    """
    if not isinstance(user_path, (str, Path)):
        raise PathTraversalError(f"Unsupported path type: {type(user_path).__name__}")

    user_str = str(user_path)
    _reject_unsafe_components(user_str)

    base_path = Path(base).resolve()

    up = Path(user_path)
    if up.is_absolute() or user_str.startswith(("/", "\\")):
        raise PathTraversalError(f"Absolute path not allowed: {user_path!r}")

    candidate = (base_path / up).resolve()
    try:
        candidate.relative_to(base_path)
    except ValueError as exc:
        raise PathTraversalError(
            f"Path {user_path!r} escapes base {str(base_path)!r}"
        ) from exc
    return candidate


def normalize_under_base(
    path_str: Optional[str],
    base_dir: PathLike,
    *,
    allow_absolute: bool = True,
) -> Optional[Path]:
    """Return the resolved path under ``base_dir`` or ``None`` on failure.

    Lenient counterpart to :func:`safe_join`: meant for HTTP handlers that want
    to turn traversal attempts into a friendly 403 instead of an exception.

    ``allow_absolute=True`` preserves the legacy contract of ``validate_path``
    (absolute inputs are resolved directly and then verified to live under
    ``base_dir``). Pass ``False`` to force a call-site identical to
    :func:`safe_join` behavior.
    """
    if not isinstance(path_str, str) or not path_str:
        return None

    try:
        _reject_unsafe_components(path_str)
    except PathTraversalError:
        return None

    try:
        base_resolved = Path(base_dir).resolve()
        requested = Path(path_str)
        if requested.is_absolute():
            if not allow_absolute:
                return None
            resolved = requested.resolve()
        else:
            resolved = (base_resolved / requested).resolve()
        resolved.relative_to(base_resolved)
        return resolved
    except (OSError, RuntimeError, ValueError, TypeError):
        return None


def is_within(base: PathLike, candidate: PathLike) -> bool:
    """Return True if ``candidate`` resolves under ``base``."""
    try:
        Path(candidate).resolve().relative_to(Path(base).resolve())
        return True
    except ValueError:
        return False


__all__ = [
    "PathTraversalError",
    "is_within",
    "normalize_under_base",
    "safe_join",
]
