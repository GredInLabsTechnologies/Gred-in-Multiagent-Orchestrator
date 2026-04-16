"""Unit tests for cross-compile helpers in ``scripts/package_core_runtime.py``.

Plan E2E_ENGINEERING_PLAN_20260416_RUNTIME_CROSS_COMPILE §Change 1 + 2.

Validan:
- Cada RuntimeTarget que entra en la matrix CI tiene asset
  python-build-standalone mapeado.
- Cada target tiene pip --platform tag mapeado.
- Los argumentos pip construidos por ``_install_wheels_cross`` incluyen
  ``--only-binary=:all:`` y los tags correctos.
- URL del standalone usa HTTPS y el tag de release pineado.
- ``cmd_build`` con --python-source=host sigue rechazando cross-targets.
"""
from __future__ import annotations

import importlib.util
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

_REPO_ROOT = Path(__file__).resolve().parents[2]
_SCRIPT = _REPO_ROOT / "scripts" / "package_core_runtime.py"


@pytest.fixture(scope="module")
def pcr():
    spec = importlib.util.spec_from_file_location("pcr_test", _SCRIPT)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_standalone_assets_cover_all_enum_values(pcr):
    """Every RuntimeTarget publicly advertised must have a standalone asset."""
    from tools.gimo_server.models.runtime import RuntimeTarget
    for target in RuntimeTarget:
        assert target.value in pcr._STANDALONE_ASSETS, (
            f"target {target.value} lacks python-build-standalone asset mapping"
        )


def test_pip_platform_tags_cover_all_enum_values(pcr):
    from tools.gimo_server.models.runtime import RuntimeTarget
    for target in RuntimeTarget:
        assert target.value in pcr._PIP_PLATFORM_TAGS, (
            f"target {target.value} lacks pip --platform tag mapping"
        )


def test_standalone_url_is_https_and_pinned(pcr):
    from tools.gimo_server.models.runtime import RuntimeTarget
    url = pcr._standalone_url(RuntimeTarget.android_arm64)
    assert url.startswith("https://github.com/astral-sh/python-build-standalone/releases/download/")
    assert pcr._STANDALONE_RELEASE in url
    assert "aarch64-unknown-linux-gnu" in url


def test_install_wheels_cross_builds_expected_pip_args(pcr, tmp_path):
    from tools.gimo_server.models.runtime import RuntimeTarget

    captured = {}

    def fake_run(args, check=True):
        captured["args"] = args
        captured["check"] = check
        return MagicMock()

    with patch.object(pcr.subprocess, "run", side_effect=fake_run):
        pcr._install_wheels_cross(
            requirements=tmp_path / "requirements.txt",
            site_packages=tmp_path / "site-packages",
            target=RuntimeTarget.android_arm64,
            python_version="3.13",
        )

    args = captured["args"]
    assert "--only-binary" in args and ":all:" in args, (
        "cross-compile debe forzar --only-binary=:all: (wheel-only)"
    )
    assert "--python-version" in args and "3.13" in args
    assert "--platform" in args
    assert "manylinux2014_aarch64" in args, (
        "android-arm64 target debe usar manylinux2014_aarch64 pip tag"
    )
    # Intencionalmente NO pasamos --implementation/--abi: eso excluye wheels
    # pure-Python (py3-none-any) y muchas deps GIMO son pure-Python.
    assert "--implementation" not in args, (
        "--implementation rompe wheels pure-Python; plan CROSS_COMPILE lo quita deliberadamente"
    )
    assert "--abi" not in args, (
        "--abi rompe wheels pure-Python; plan CROSS_COMPILE lo quita deliberadamente"
    )
    assert captured["check"] is True


def test_install_wheels_cross_fails_for_unmapped_target(pcr, tmp_path):
    class _FakeTarget:
        value = "does-not-exist"

    with pytest.raises(SystemExit) as excinfo:
        pcr._install_wheels_cross(
            requirements=tmp_path / "r.txt",
            site_packages=tmp_path / "sp",
            target=_FakeTarget(),
            python_version="3.13",
        )
    assert "pip --platform tag" in str(excinfo.value)


def test_standalone_url_fails_for_unmapped_target(pcr):
    class _FakeTarget:
        value = "does-not-exist"

    with pytest.raises(SystemExit) as excinfo:
        pcr._standalone_url(_FakeTarget())
    assert "python-build-standalone" in str(excinfo.value)


def test_cmd_build_rejects_cross_target_with_host_source(pcr, tmp_path):
    """Con --python-source=host (default), cross-compile debe fallar limpio."""
    import argparse

    args = argparse.Namespace(
        target="android-arm64",
        output=str(tmp_path / "out"),
        compression="xz",
        runtime_version="0.1.0",
        signing_key="dummy",
        builder="test",
        python_source="host",
    )
    with pytest.raises(SystemExit) as excinfo:
        pcr.cmd_build(args)
    msg = str(excinfo.value).lower()
    assert "cross-compilation" in msg
    assert "--python-source" in msg


def test_argparser_has_python_source_flag(pcr):
    parser = pcr._build_argparser()
    # Drill down to the build subparser
    subparsers_action = next(a for a in parser._actions if isinstance(a, argparse_sub_action()))
    build_parser = subparsers_action.choices["build"]
    opt_strings = {opt for action in build_parser._actions for opt in action.option_strings}
    assert "--python-source" in opt_strings


def argparse_sub_action():
    """Return the argparse ``_SubParsersAction`` type (varies by Python version)."""
    import argparse
    return argparse._SubParsersAction
