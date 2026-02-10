"""
Análisis de dependencias no usadas en el proyecto.

Este script analiza requirements.txt y busca referencias a cada paquete
en el código fuente para identificar dependencias potencialmente no utilizadas.
"""

import re
import subprocess
from pathlib import Path
from typing import List, Tuple

# Mapeo de nombres de paquetes a módulos de importación
PACKAGE_TO_MODULE = {
    "opencv-python": "cv2",
    "opencv-python-headless": "cv2",
    "pillow": "PIL",
    "python-multipart": "multipart",
    "python-dotenv": "dotenv",
    "uvicorn": "uvicorn",
    "fastapi": "fastapi",
    "pydantic": "pydantic",
    "starlette": "starlette",
    "requests": "requests",
    "pytest": "pytest",
    "pytest-cov": "pytest_cov",
    "pytest-asyncio": "pytest_asyncio",
    "httpx": "httpx",
    "aiofiles": "aiofiles",
    "pyyaml": "yaml",
    "google-generativeai": "google.generativeai",
    "reportlab": "reportlab",
    "xhtml2pdf": "xhtml2pdf",
    "pypdf": "pypdf",
    "torch": "torch",
    "torchaudio": "torchaudio",
    "torchvision": "torchvision",
    "transformers": "transformers",
    "onnxruntime-gpu": "onnxruntime",
    "onnxruntime": "onnxruntime",
    "scikit-learn": "sklearn",
    "pandas": "pandas",
    "numpy": "numpy",
    "scipy": "scipy",
    "matplotlib": "matplotlib",
    "seaborn": "seaborn",
}


def parse_requirements(requirements_file: Path) -> List[Tuple[str, str]]:
    """Parse requirements.txt y extrae paquetes con versiones."""
    packages = []

    with open(requirements_file, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            # Ignorar comentarios y líneas vacías
            if not line or line.startswith("#"):
                continue

            # Extraer nombre de paquete (antes de ==, >=, etc.)
            match = re.match(r"^([a-zA-Z0-9_-]+)", line)
            if match:
                package_name = match.group(1).lower()
                packages.append((package_name, line))

    return packages


def get_module_name(package_name: str) -> str:
    """Obtiene el nombre del módulo a partir del nombre del paquete."""
    # Primero verificar el mapeo manual
    if package_name in PACKAGE_TO_MODULE:
        return PACKAGE_TO_MODULE[package_name]

    # Por defecto, usar el nombre del paquete (reemplazar guiones con guiones bajos)
    return package_name.replace("-", "_")


def search_imports(module_name: str, source_dirs: List[Path]) -> List[str]:
    """Busca imports del módulo en los directorios de código fuente."""
    matches = []

    # Patrones de búsqueda
    patterns = [
        f"import {module_name}",
        f"from {module_name}",
        f"import {module_name.split('.')[0]}",  # Para módulos con punto
    ]

    for source_dir in source_dirs:
        for pattern in patterns:
            try:
                # Usar grep recursivo para buscar imports
                result = subprocess.run(
                    ["grep", "-r", "-l", "--include=*.py", pattern, str(source_dir)],
                    capture_output=True,
                    text=True,
                    timeout=10,
                )

                if result.returncode == 0 and result.stdout.strip():
                    files = result.stdout.strip().split("\n")
                    matches.extend(files)
            except (subprocess.TimeoutExpired, FileNotFoundError):
                # Si grep no está disponible, usar búsqueda manual
                for py_file in source_dir.rglob("*.py"):
                    try:
                        content = py_file.read_text(encoding="utf-8")
                        if pattern in content:
                            matches.append(str(py_file))
                    except Exception:
                        pass

    return list(set(matches))  # Eliminar duplicados


def analyze_dependencies(repo_root: Path):
    """Analiza dependencias y genera reporte."""

    requirements_file = repo_root / "requirements.txt"
    if not requirements_file.exists():
        print(f"[ERROR] No se encontro requirements.txt en {repo_root}")
        return

    # Directorios de código fuente a analizar
    source_dirs = [
        repo_root / "tools" / "gimo_server",
        repo_root / "tests",
        repo_root / "scripts",
    ]

    # Filtrar solo los que existen
    source_dirs = [d for d in source_dirs if d.exists()]

    print("[*] Analizando dependencias...\n")
    print(f"Requirements: {requirements_file}")
    print(f"Directorios de codigo: {[str(d) for d in source_dirs]}\n")
    print("=" * 80)

    packages = parse_requirements(requirements_file)

    unused_packages = []
    used_packages = []
    unclear_packages = []

    for package_name, requirement_line in packages:
        module_name = get_module_name(package_name)
        matches = search_imports(module_name, source_dirs)

        if matches:
            used_packages.append((package_name, module_name, matches))
            status = "[OK] USADO"
        else:
            # Paquetes que podrían ser dependencias indirectas
            if package_name in [
                "certifi",
                "charset-normalizer",
                "idna",
                "urllib3",
                "typing-extensions",
                "annotated-types",
                "pydantic-core",
                "anyio",
                "sniffio",
                "h11",
                "click",
                "setuptools",
                "wheel",
                "packaging",
                "platformdirs",
                "filelock",
            ]:
                unclear_packages.append(
                    (package_name, module_name, "Dependencia indirecta probable")
                )
                status = "[?] INDIRECTA"
            else:
                unused_packages.append((package_name, module_name, requirement_line))
                status = "[X] NO USADO"

        print(f"{status:15} | {package_name:30} | módulo: {module_name}")

    # Resumen
    print("\n" + "=" * 80)
    print("\nRESUMEN\n")
    print(f"Total de paquetes: {len(packages)}")
    print(f"[OK] Paquetes usados: {len(used_packages)}")
    print(f"[?] Dependencias indirectas: {len(unclear_packages)}")
    print(f"[X] Paquetes potencialmente no usados: {len(unused_packages)}")

    # Paquetes no usados (más detalle)
    if unused_packages:
        print("\n" + "=" * 80)
        print("\nPAQUETES POTENCIALMENTE NO USADOS:\n")

        for package_name, module_name, requirement_line in unused_packages:
            print(f"  - {package_name}")
            print(f"    Linea en requirements.txt: {requirement_line}")
            print(f"    Modulo buscado: {module_name}")
            print()

    # Paquetes sospechosos específicos (del plan)
    print("\n" + "=" * 80)
    print("\nANALISIS DE PAQUETES SOSPECHOSOS (del plan):\n")

    suspicious = [
        "torch",
        "transformers",
        "opencv-python",
        "opencv-python-headless",
        "onnxruntime-gpu",
        "google-generativeai",
    ]

    for pkg in suspicious:
        found_in_unused = any(p[0] == pkg for p in unused_packages)
        found_in_used = any(p[0] == pkg for p in used_packages)

        if found_in_unused:
            print(f"  [X] {pkg:30} - NO USADO - Candidato para remocion")
        elif found_in_used:
            files = [p[2] for p in used_packages if p[0] == pkg][0]
            print(f"  [OK] {pkg:30} - USADO en {len(files)} archivo(s)")
        else:
            print(f"  [?] {pkg:30} - No encontrado en requirements.txt")

    # Guardar reporte
    report_file = repo_root / "dependency_audit_report.txt"
    with open(report_file, "w", encoding="utf-8") as f:
        f.write("REPORTE DE AUDITORÍA DE DEPENDENCIAS\n")
        f.write("=" * 80 + "\n\n")
        f.write(f"Total de paquetes: {len(packages)}\n")
        f.write(f"Paquetes usados: {len(used_packages)}\n")
        f.write(f"Dependencias indirectas: {len(unclear_packages)}\n")
        f.write(f"Paquetes NO usados: {len(unused_packages)}\n\n")

        f.write("\nPAQUETES NO USADOS:\n")
        f.write("-" * 80 + "\n")
        for package_name, module_name, requirement_line in unused_packages:
            f.write(f"{package_name}\n")
            f.write(f"  {requirement_line}\n\n")

    print(f"\nReporte guardado en: {report_file}")
    print("\nAnalisis completado")


if __name__ == "__main__":
    # scripts/dev/*.py -> repo root
    repo_root = Path(__file__).parent.parent.parent
    analyze_dependencies(repo_root)
