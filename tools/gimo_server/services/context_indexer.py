import json
from pathlib import Path
from typing import List

from tools.gimo_server.ops_models import RepoContext

class ContextIndexer:
    """Service to analyze the repository and build the RepoContext for the LLM."""

    PKG_JSON = "package.json"
    PYPROJECT = "pyproject.toml"
    REQ_TXT = "requirements.txt"

    @staticmethod
    def build_context(workspace_root: str) -> RepoContext:
        root = Path(workspace_root)
        stack: set[str] = set()
        commands: set[str] = set()
        paths: set[str] = set()
        
        ContextIndexer._detect_nodejs(root, stack, commands)
        ContextIndexer._detect_python(root, stack, commands)
        ContextIndexer._detect_go(root, stack, commands)
        ContextIndexer._detect_docker(root, stack, commands)
        ContextIndexer._detect_paths(root, paths)

        return RepoContext(
            stack=sorted(list(stack)),
            commands=sorted(list(commands)),
            paths_of_interest=sorted(list(paths)),
            env_notes="Inferred automatically by ContextIndexer."
        )

    @staticmethod
    def _detect_nodejs(root: Path, stack: set[str], commands: set[str]) -> None:
        package_json = root / ContextIndexer.PKG_JSON
        if not package_json.exists():
            return
        stack.add("Node.js")
        try:
            pkg_data = json.loads(package_json.read_text(encoding="utf-8"))
            deps = list(pkg_data.get("dependencies", {}).keys()) + list(pkg_data.get("devDependencies", {}).keys())
            for fw in ["react", "vue", "next", "svelte", "express", "fastify", "vite", "tailwindcss"]:
                if fw in deps or f"@{fw}" in deps:
                    stack.add(fw.capitalize())
            
            commands.add("npm install")
            scripts = pkg_data.get("scripts", {})
            for cmd in ["test", "lint", "build", "dev"]:
                if cmd in scripts:
                    commands.add(f"npm run {cmd}")
        except Exception:
            pass

    @staticmethod
    def _detect_python(root: Path, stack: set[str], commands: set[str]) -> None:
        has_pyproject = (root / ContextIndexer.PYPROJECT).exists()
        has_reqs = (root / ContextIndexer.REQ_TXT).exists()
        
        if not has_pyproject and not has_reqs:
            return
            
        stack.add("Python")
        if has_pyproject:
            try:
                content = (root / ContextIndexer.PYPROJECT).read_text(encoding="utf-8").lower()
                for fw in ["fastapi", "django", "flask", "pytest", "poetry"]:
                    if fw in content:
                        stack.add(fw.capitalize())
                        
                if "ruff" in content:
                    commands.add("ruff check .")
                elif "flake8" in content:
                    commands.add("flake8 .")
                elif "pylint" in content:
                    commands.add("pylint src")
            except Exception:
                pass
                
        commands.add(f"pip install -r {ContextIndexer.REQ_TXT}" if has_reqs else "pip install .")
        commands.add("pytest tests")

    @staticmethod
    def _detect_go(root: Path, stack: set[str], commands: set[str]) -> None:
        if (root / "go.mod").exists():
            stack.add("Go")
            commands.add("go build")
            commands.add("go test ./...")

    @staticmethod
    def _detect_docker(root: Path, stack: set[str], commands: set[str]) -> None:
        if (root / "Dockerfile").exists():
            stack.add("Docker")
            commands.add("docker build .")

    @staticmethod
    def _detect_paths(root: Path, paths: set[str]) -> None:
        for d in ["src", "lib", "tools", "tests", "docs", "apps", "packages", "scripts"]:
            if (root / d).is_dir():
                paths.add(f"{d}/")
        if not paths:
            paths.add(".")

    @staticmethod
    def extract_file_contents(workspace_root: str, path_scope: List[str]) -> str:
        """Reads specific files from the workspace and formats them for the LLM context."""
        root = Path(workspace_root).resolve()
        contents = []
        for path_str in path_scope:
            path_str_safe = path_str.lstrip('/')
            path = (root / path_str_safe).resolve()
            
            if not str(path).startswith(str(root)):
                contents.append(f"--- {path_str} ---\n[Access denied: Path outside workspace]\n")
                continue
                
            if path.is_file():
                try:
                    text_content = path.read_text(encoding="utf-8")
                    contents.append(f"--- {path_str} ---\n{text_content}\n")
                except Exception as e:
                    contents.append(f"--- {path_str} ---\n[Error reading file: {e}]\n")
            else:
                contents.append(f"--- {path_str} ---\n[File not found]\n")
        return "\n".join(contents)
