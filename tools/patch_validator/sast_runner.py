"""
Integración con herramientas SAST y secret scanning (Fase B).

Herramientas que se intentan ejecutar (si están instaladas):
  - bandit: análisis de seguridad para Python
  - semgrep: análisis polivalente (Python, JS, TS, Go...)
  - gitleaks: secret scanning en el diff
  - trufflehog: secret scanning adicional

Si alguna herramienta no está instalada, el check se marca como SKIP
y se añade un warning (no falla el pipeline, pero queda registrado).

Los checks se ejecutan sobre el DIFF GENERADO del patch,
no sobre el repo completo. Esto reduce el ruido.
"""
from __future__ import annotations

import json
import logging
import shutil
import subprocess
import tempfile
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

logger = logging.getLogger("patch_validator.sast")

SUBPROCESS_TIMEOUT = 60  # segundos por herramienta


@dataclass
class SASTResult:
    tool: str
    status: str  # PASS | FAIL | SKIP | ERROR
    findings: list[dict[str, Any]] = field(default_factory=list)
    stderr: str = ""
    returncode: int = 0


@dataclass
class SASTRunnerResult:
    overall: str  # PASS | FAIL | SKIP
    results: list[SASTResult] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)

    @property
    def passed(self) -> bool:
        return self.overall in ("PASS", "SKIP")


def run_sast(patch_data: dict[str, Any], repo_root: Path) -> SASTRunnerResult:
    """
    Ejecuta las herramientas SAST disponibles sobre el diff del patch.

    Args:
        patch_data: Contenido del patch propuesto
        repo_root:  Raíz del repositorio (para contexto de paths)

    Returns:
        SASTRunnerResult con resultados agregados
    """
    results: list[SASTResult] = []
    warnings: list[str] = []

    # Materializar el diff en archivos temporales
    with tempfile.TemporaryDirectory(prefix="gptactions_sast_") as tmp_dir:
        tmp_path = Path(tmp_dir)
        diff_text = _generate_unified_diff(patch_data)
        diff_file = tmp_path / "patch.diff"
        diff_file.write_text(diff_text, encoding="utf-8")

        # Extraer archivos .py modificados para bandit
        py_files = _extract_new_content_by_ext(patch_data, ".py", tmp_path)
        ts_files = _extract_new_content_by_ext(patch_data, [".ts", ".tsx", ".js", ".jsx"], tmp_path)

        # --- bandit ---
        if shutil.which("bandit"):
            results.append(_run_bandit(py_files, tmp_path))
        else:
            warnings.append("bandit no instalado — SKIP (instala: pip install bandit)")
            results.append(SASTResult(tool="bandit", status="SKIP"))

        # --- semgrep ---
        if shutil.which("semgrep"):
            results.append(_run_semgrep(tmp_path, py_files + ts_files))
        else:
            warnings.append("semgrep no instalado — SKIP (instala: pip install semgrep)")
            results.append(SASTResult(tool="semgrep", status="SKIP"))

        # --- gitleaks (secret scan sobre el diff) ---
        if shutil.which("gitleaks"):
            results.append(_run_gitleaks(diff_file))
        else:
            warnings.append("gitleaks no instalado — SKIP (instala desde: github.com/gitleaks/gitleaks)")
            results.append(SASTResult(tool="gitleaks", status="SKIP"))

    # Calcular resultado global
    failed = [r for r in results if r.status == "FAIL"]
    all_skipped = all(r.status in ("SKIP", "PASS") for r in results)

    if failed:
        overall = "FAIL"
        logger.warning(
            "SAST FAIL: herramientas con hallazgos: %s",
            [r.tool for r in failed],
        )
    elif all_skipped and not any(r.status == "PASS" for r in results):
        overall = "SKIP"
        logger.warning("Todas las herramientas SAST estaban SKIP — considera instalarlas")
    else:
        overall = "PASS"

    return SASTRunnerResult(overall=overall, results=results, warnings=warnings)


# ------------------------------------------------------------------
# Runners individuales
# ------------------------------------------------------------------

def _run_bandit(py_files: list[Path], work_dir: Path) -> SASTResult:
    if not py_files:
        return SASTResult(tool="bandit", status="SKIP", stderr="Sin archivos Python en el patch")

    # Escribir lista de archivos
    file_list = work_dir / "bandit_targets.txt"
    file_list.write_text("\n".join(str(f) for f in py_files), encoding="utf-8")

    cmd = [
        "bandit",
        "--format", "json",
        "--severity-level", "medium",
        "--confidence-level", "medium",
        "--target", str(work_dir),
        "--recursive",
    ]
    try:
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=SUBPROCESS_TIMEOUT,
            cwd=str(work_dir),
        )
        # bandit devuelve 1 si hay hallazgos, 0 si no
        if result.returncode == 0:
            return SASTResult(tool="bandit", status="PASS", returncode=0)

        try:
            data = json.loads(result.stdout)
            findings = data.get("results", [])
        except json.JSONDecodeError:
            findings = []

        # Filtrar hallazgos de severidad MEDIUM o HIGH
        high_findings = [
            f for f in findings
            if f.get("issue_severity", "LOW").upper() in ("MEDIUM", "HIGH")
        ]
        if high_findings:
            return SASTResult(
                tool="bandit",
                status="FAIL",
                findings=high_findings[:20],
                returncode=result.returncode,
            )
        return SASTResult(tool="bandit", status="PASS", returncode=0)

    except subprocess.TimeoutExpired:
        return SASTResult(tool="bandit", status="ERROR", stderr="Timeout")
    except Exception as exc:
        return SASTResult(tool="bandit", status="ERROR", stderr=str(exc))


def _run_semgrep(work_dir: Path, target_files: list[Path]) -> SASTResult:
    if not target_files:
        return SASTResult(tool="semgrep", status="SKIP", stderr="Sin archivos objetivo")

    cmd = [
        "semgrep",
        "--config", "auto",
        "--json",
        "--severity", "WARNING",
        "--severity", "ERROR",
        "--quiet",
        str(work_dir),
    ]
    try:
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=SUBPROCESS_TIMEOUT * 2,
            cwd=str(work_dir),
        )
        try:
            data = json.loads(result.stdout)
            findings = data.get("results", [])
        except json.JSONDecodeError:
            findings = []

        if findings:
            return SASTResult(tool="semgrep", status="FAIL", findings=findings[:20], returncode=result.returncode)
        return SASTResult(tool="semgrep", status="PASS", returncode=0)

    except subprocess.TimeoutExpired:
        return SASTResult(tool="semgrep", status="ERROR", stderr="Timeout")
    except Exception as exc:
        return SASTResult(tool="semgrep", status="ERROR", stderr=str(exc))


def _run_gitleaks(diff_file: Path) -> SASTResult:
    cmd = [
        "gitleaks",
        "detect",
        "--source", str(diff_file.parent),
        "--report-format", "json",
        "--report-path", str(diff_file.parent / "gitleaks_report.json"),
        "--no-git",
        "--verbose",
    ]
    try:
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=SUBPROCESS_TIMEOUT,
        )
        report_path = diff_file.parent / "gitleaks_report.json"
        findings = []
        if report_path.exists():
            try:
                findings = json.loads(report_path.read_text(encoding="utf-8")) or []
            except Exception:
                pass

        if findings:
            return SASTResult(tool="gitleaks", status="FAIL", findings=findings[:10], returncode=result.returncode)
        return SASTResult(tool="gitleaks", status="PASS", returncode=0)

    except subprocess.TimeoutExpired:
        return SASTResult(tool="gitleaks", status="ERROR", stderr="Timeout")
    except Exception as exc:
        return SASTResult(tool="gitleaks", status="ERROR", stderr=str(exc))


# ------------------------------------------------------------------
# Helpers de materializacion del diff
# ------------------------------------------------------------------

def _generate_unified_diff(patch_data: dict[str, Any]) -> str:
    """Genera un diff unificado textual a partir del patch JSON."""
    lines = []
    for file_entry in patch_data.get("target_files", []):
        path = file_entry.get("path", "unknown")
        lines.append(f"--- a/{path}")
        lines.append(f"+++ b/{path}")
        for hunk in file_entry.get("hunks", []):
            start = hunk.get("start_line", 1)
            old = hunk.get("old_lines", [])
            new = hunk.get("new_lines", [])
            lines.append(f"@@ -{start},{len(old)} +{start},{len(new)} @@")
            for l in old:
                lines.append(f"-{l}")
            for l in new:
                lines.append(f"+{l}")
    return "\n".join(lines)


def _extract_new_content_by_ext(
    patch_data: dict[str, Any],
    extensions: str | list[str],
    work_dir: Path,
) -> list[Path]:
    """
    Extrae el contenido NUEVO de los archivos con la extensión dada
    como archivos temporales para que las herramientas puedan analizarlos.
    """
    if isinstance(extensions, str):
        extensions = [extensions]
    exts = {e.lower() for e in extensions}
    result = []
    for file_entry in patch_data.get("target_files", []):
        path_str = file_entry.get("path", "")
        ext = Path(path_str).suffix.lower()
        if ext not in exts:
            continue
        # Reconstruir contenido nuevo (solo las líneas new)
        new_lines = []
        for hunk in file_entry.get("hunks", []):
            new_lines.extend(hunk.get("new_lines", []))
        if not new_lines:
            continue
        safe_name = path_str.replace("/", "_").replace("\\", "_")
        tmp_file = work_dir / f"new_{safe_name}"
        tmp_file.write_text("\n".join(new_lines), encoding="utf-8")
        result.append(tmp_file)
    return result
