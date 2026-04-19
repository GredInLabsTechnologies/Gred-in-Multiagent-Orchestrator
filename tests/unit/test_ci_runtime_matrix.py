"""Audit estático del job ``runtime-packaging`` en ``.github/workflows/ci.yml``.

Step 9 del plan E2E_ENGINEERING_PLAN_20260416_RUNTIME_PACKAGING.

No podemos ejecutar el workflow desde pytest, pero sí garantizamos que contiene
las dos entradas matrix del MVP (``android-arm64`` + ``windows-x86_64``) y que
cada entrada invoca build + verify + smoke. Si un refactor accidentalmente
elimina una, esta guarda lo detecta.
"""
from __future__ import annotations

from pathlib import Path

import pytest

_REPO_ROOT = Path(__file__).resolve().parents[2]
_CI_FILE = _REPO_ROOT / ".github" / "workflows" / "ci.yml"


@pytest.fixture(scope="module")
def ci_yaml() -> dict:
    if not _CI_FILE.exists():
        pytest.skip(f"ci workflow not present: {_CI_FILE}")
    try:
        import yaml
    except ImportError:
        pytest.skip("PyYAML not installed")
    return yaml.safe_load(_CI_FILE.read_text(encoding="utf-8"))


def test_runtime_packaging_job_registered(ci_yaml: dict) -> None:
    assert "runtime-packaging" in ci_yaml["jobs"], (
        "El job runtime-packaging debe existir para que el MVP tenga cobertura CI "
        "en android-arm64 + windows-x86_64."
    )


def test_matrix_contains_all_targets(ci_yaml: dict) -> None:
    """Plan CROSS_COMPILE: matrix ahora cubre 4 targets reales."""
    job = ci_yaml["jobs"]["runtime-packaging"]
    matrix = job["strategy"]["matrix"]["include"]
    targets = {entry["target"] for entry in matrix}
    for expected in ("android-arm64", "linux-x86_64", "windows-x86_64", "darwin-arm64"):
        assert expected in targets, f"Falta target {expected!r} en matrix CI."


def test_matrix_runners_are_platform_appropriate(ci_yaml: dict) -> None:
    job = ci_yaml["jobs"]["runtime-packaging"]
    matrix = job["strategy"]["matrix"]["include"]
    for entry in matrix:
        target = entry["target"]
        runner = entry["runner"]
        if target == "windows-x86_64":
            assert runner.startswith("windows-"), (
                f"{target} debe correr en windows-* runner, no en {runner!r}."
            )
        elif target == "darwin-arm64":
            assert runner.startswith("macos-"), (
                f"{target} debe correr en macos-* runner (Apple Silicon), no en {runner!r}."
            )
        elif target in ("android-arm64", "linux-x86_64"):
            # ubuntu-latest: linux-x86_64 = host; android-arm64 = cross-compile
            # via python-build-standalone aarch64-unknown-linux-gnu + pip --platform.
            assert runner.startswith("ubuntu-"), (
                f"{target} usa ubuntu-* runner (host o cross desde Linux)."
            )


def test_android_target_uses_cross_compile(ci_yaml: dict) -> None:
    """Plan CROSS_COMPILE §Change 3 — android-arm64 debe usar python-source=standalone.

    El MVP empaquetaba host Python, lo cual producía un bundle x86_64
    etiquetado como android-arm64. Este test ancla que la matrix usa
    cross-compile real.
    """
    job = ci_yaml["jobs"]["runtime-packaging"]
    matrix = job["strategy"]["matrix"]["include"]
    android_entry = next(e for e in matrix if e["target"] == "android-arm64")
    assert android_entry.get("python_source") == "standalone", (
        "android-arm64 debe usar --python-source=standalone para cross-compile real."
    )
    assert android_entry.get("package_target") == "android-arm64", (
        "android-arm64 matrix debe pasar --target android-arm64 al productor, no 'host'."
    )


def test_host_targets_still_work(ci_yaml: dict) -> None:
    """Los targets que son nativos del runner usan --python-source=host (sin regresión)."""
    job = ci_yaml["jobs"]["runtime-packaging"]
    matrix = job["strategy"]["matrix"]["include"]
    for target in ("linux-x86_64", "windows-x86_64", "darwin-arm64"):
        entry = next(e for e in matrix if e["target"] == target)
        assert entry.get("python_source") == "host", (
            f"{target} debe usar --python-source=host (el runner es nativo)."
        )


def test_matrix_steps_cover_build_verify_smoke(ci_yaml: dict) -> None:
    job = ci_yaml["jobs"]["runtime-packaging"]
    step_names = [step.get("name", "") for step in job["steps"]]
    joined = " | ".join(step_names).lower()
    assert "build runtime bundle" in joined, "Falta step 'Build runtime bundle'."
    assert "verify bundle" in joined, "Falta step 'Verify bundle'."
    assert "runtime_bootstrap" in joined or "smoke" in joined, (
        "Falta step smoke de runtime_bootstrap (roundtrip)."
    )


def test_bundle_artifacts_uploaded(ci_yaml: dict) -> None:
    job = ci_yaml["jobs"]["runtime-packaging"]
    upload_steps = [
        s for s in job["steps"]
        if "upload" in s.get("name", "").lower()
        or s.get("uses", "").startswith("actions/upload-artifact")
    ]
    assert upload_steps, "No hay step de upload-artifact — el bundle se pierde tras el run."


def test_matrix_signing_keypair_ephemeral(ci_yaml: dict) -> None:
    """No queremos commits accidentales de claves persistentes en el repo."""
    job = ci_yaml["jobs"]["runtime-packaging"]
    steps = [str(s) for s in job["steps"]]
    text = " ".join(steps).lower()
    assert "generate ephemeral" in text or "ed25519privatekey.generate" in text, (
        "El keypair del CI debe ser efímero (generado por step), no venir de repo."
    )
