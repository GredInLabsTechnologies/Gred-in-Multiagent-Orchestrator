"""Static audit of ``apps/android/gimomesh/app/build.gradle.kts``.

Step 7 del plan E2E_ENGINEERING_PLAN_20260416_RUNTIME_PACKAGING (Change 7).

No podemos ejecutar gradle aquí (toolchain Android), pero sí podemos garantizar
contractualmente que el build contiene:

* La tarea ``packageCoreRuntime`` registrada.
* La tarea copia desde ``runtime-assets/`` a ``src/main/assets/runtime/``.
* ``noCompress`` incluye ``"xz"`` — la APK no re-comprime el tarball.
* ``mergeDebugAssets`` y ``mergeReleaseAssets`` dependen de ``packageCoreRuntime``.
* Referencia al productor Python (scripts/package_core_runtime.py) en el mensaje
  de error — operator-ergonomic.

Si el gradle file se refactoriza y alguno de estos contratos se rompe, el test
falla con mensaje accionable. Así el CI matrix (step 9) no se sorprende.
"""
from __future__ import annotations

from pathlib import Path

import pytest

_REPO_ROOT = Path(__file__).resolve().parents[2]
_GRADLE_FILE = _REPO_ROOT / "apps" / "android" / "gimomesh" / "app" / "build.gradle.kts"


@pytest.fixture(scope="module")
def gradle_content() -> str:
    if not _GRADLE_FILE.exists():
        pytest.skip(f"gradle file not present: {_GRADLE_FILE}")
    return _GRADLE_FILE.read_text(encoding="utf-8")


def test_package_core_runtime_task_registered(gradle_content: str) -> None:
    assert 'tasks.register<Copy>("packageCoreRuntime")' in gradle_content, (
        "La tarea :app:packageCoreRuntime debe estar registrada como tipo Copy."
    )


def test_no_compress_xz(gradle_content: str) -> None:
    assert 'noCompress' in gradle_content, "androidResources.noCompress debe estar presente."
    assert '"xz"' in gradle_content, "El tarball GIMO usa compresión XZ — aapt no debe re-comprimir."


def test_copy_source_and_destination(gradle_content: str) -> None:
    assert "runtime-assets" in gradle_content, (
        "packageCoreRuntime debe leer de runtime-assets/ (producido por scripts/package_core_runtime.py)."
    )
    assert 'src/main/assets/runtime' in gradle_content, (
        "packageCoreRuntime debe escribir a src/main/assets/runtime/ para que ShellEnvironment lo encuentre."
    )


def test_required_artifacts_in_copy(gradle_content: str) -> None:
    for artifact in ("gimo-core-runtime.json", "gimo-core-runtime.tar.xz", "gimo-core-runtime.sig"):
        assert artifact in gradle_content, (
            f"Missing artifact {artifact!r} en include() de packageCoreRuntime. "
            "El bundle tiene 3 ficheros (manifest + tarball + sig) — los 3 deben copiarse."
        )


def test_merge_assets_depends_on_package_core_runtime(gradle_content: str) -> None:
    assert 'mergeDebugAssets' in gradle_content, "mergeDebugAssets debe depender de packageCoreRuntime."
    assert 'mergeReleaseAssets' in gradle_content, "mergeReleaseAssets debe depender de packageCoreRuntime."
    assert 'dependsOn(packageCoreRuntime)' in gradle_content, (
        "Wire de dependencia roto — mergeAssets no corre packageCoreRuntime antes."
    )


def test_error_message_references_python_producer(gradle_content: str) -> None:
    """Si el bundle no existe, el error debe decir cómo producirlo localmente."""
    assert 'scripts/package_core_runtime.py' in gradle_content, (
        "El mensaje de GradleException debe referenciar scripts/package_core_runtime.py "
        "para que el operator sepa cómo desbloquearse sin leer el plan entero."
    )


def test_fetch_runtime_bundle_task_registered(gradle_content: str) -> None:
    """Plan CROSS_COMPILE §Change 4 — fetchRuntimeBundle task debe existir."""
    assert '"fetchRuntimeBundle"' in gradle_content, (
        "Falta la tarea :app:fetchRuntimeBundle que baja el bundle desde CI artifact."
    )
    assert 'GIMO_RUNTIME_BUNDLE_URL' in gradle_content, (
        "fetchRuntimeBundle debe leer la URL del env var GIMO_RUNTIME_BUNDLE_URL."
    )


def test_package_core_runtime_depends_on_fetch(gradle_content: str) -> None:
    """packageCoreRuntime debe ejecutarse DESPUÉS de fetchRuntimeBundle."""
    # Con register<Copy> la dependencia se expresa como dependsOn(fetchRuntimeBundle).
    assert 'dependsOn(fetchRuntimeBundle)' in gradle_content, (
        "packageCoreRuntime debe depender de fetchRuntimeBundle para que el fetch "
        "corra antes del copy."
    )


def test_trusted_pubkey_asset_copied(gradle_content: str) -> None:
    """Plan CROSS_COMPILE §Change 5 — trusted-pubkey.pem se copia a assets/runtime/."""
    assert 'trusted-pubkey.pem' in gradle_content, (
        "packageCoreRuntime debe incluir trusted-pubkey.pem para que "
        "ShellEnvironment pueda validar firma del bundle."
    )
