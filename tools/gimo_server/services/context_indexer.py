import json
from pathlib import Path
from typing import List

from tools.gimo_server.ops_models import RepoContext

class ContextIndexer:
    """Service to analyze the repository and build the RepoContext for the LLM."""

    @staticmethod
    def build_context(workspace_root: str) -> RepoContext:
        root = Path(workspace_root)
        stack: set[str] = set()
        commands: set[str] = set()
        paths: set[str] = set()
        env_notes = "Inferred automatically by ContextIndexer."

        # Detect Node.js
        package_json = root / "package.json"
        if package_json.exists():
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

        # Detect Python
        if (root / "pyproject.toml").exists() or (root / "requirements.txt").exists():
            stack.add("Python")
            if (root / "pyproject.toml").exists():
                try:
                    content = (root / "pyproject.toml").read_text(encoding="utf-8").lower()
                    for fw in ["fastapi", "django", "flask", "pytest", "poetry"]:
                        if fw in content:
                            stack.add(fw.capitalize())
                except Exception:
                    pass
            commands.add("pip install -r requirements.txt" if (root / "requirements.txt").exists() else "pip install .")
            commands.add("pytest tests")

        # Detect Go
        if (root / "go.mod").exists():
            stack.add("Go")
            commands.add("go build")
            commands.add("go test ./...")

        # Detect Docker
        if (root / "Dockerfile").exists():
            stack.add("Docker")
            commands.add("docker build .")

        # Add top-level paths of interest
        for d in ["src", "lib", "tools", "tests", "docs", "apps", "packages", "scripts"]:
            if (root / d).is_dir():
                paths.add(f"{d}/")
                
        # Fallback if no specific paths found
        if not paths:
            paths.add(".")

        return RepoContext(
            stack=sorted(list(stack)),
            commands=sorted(list(commands)),
            paths_of_interest=sorted(list(paths)),
            env_notes=env_notes
        )
