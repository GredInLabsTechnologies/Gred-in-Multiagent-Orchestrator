from __future__ import annotations

import asyncio
import os
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional

import httpx

from ...ops_models import NormalizedModelInfo


def get_ollama_manifest_dir() -> Optional[Path]:
    env_val = os.environ.get("OLLAMA_MODELS")
    if env_val:
        path = Path(env_val)
        if (path / "manifests").exists():
            return path / "manifests"
        if path.name == "models" and path.exists() and (path / "manifests").exists():
            return path / "manifests"

    special_path = Path("D:/Ollama/models/manifests")
    if special_path.exists():
        return special_path

    defaults = [
        Path(os.environ.get("USERPROFILE", "")) / ".ollama" / "models" / "manifests",
        Path(os.environ.get("LOCALAPPDATA", "")) / "Ollama" / "models" / "manifests",
    ]
    for p in defaults:
        if p.exists():
            return p
    return None


def ollama_list_from_disk(normalize_model: Callable[..., NormalizedModelInfo]) -> List[NormalizedModelInfo]:
    manifest_dir = get_ollama_manifest_dir()
    if not manifest_dir:
        return []

    models: List[NormalizedModelInfo] = []
    try:
        lib_path = manifest_dir / "registry.ollama.ai" / "library"
        if not lib_path.exists():
            return []

        for model_dir in lib_path.iterdir():
            if model_dir.is_dir():
                model_name = model_dir.name
                for tag_file in model_dir.iterdir():
                    if tag_file.is_file():
                        tag = tag_file.name
                        model_id = f"{model_name}:{tag}"
                        models.append(
                            normalize_model(
                                model_id=model_id,
                                installed=True,
                                downloadable=True,
                            )
                        )
        return models
    except Exception:
        return []


def parse_ollama_api_item(item: Dict[str, Any], normalize_model: Callable[..., NormalizedModelInfo]) -> NormalizedModelInfo | None:
    model_id = str(item.get("name") or "").strip()
    if not model_id:
        return None
    details = item.get("details") if isinstance(item.get("details"), dict) else {}
    size = details.get("parameter_size") or item.get("size")
    return normalize_model(
        model_id=model_id,
        installed=True,
        downloadable=True,
        size=str(size) if size is not None else None,
    )


async def ollama_api_list(normalize_model: Callable[..., NormalizedModelInfo]) -> List[NormalizedModelInfo]:
    try:
        async with httpx.AsyncClient(timeout=2) as client:
            resp = await client.get("http://localhost:11434/api/tags")
            if 200 <= resp.status_code < 300:
                data = resp.json() if resp.content else {}
                models_data = data.get("models", []) if isinstance(data, dict) else []
                models = [
                    m for item in models_data
                    if (m := parse_ollama_api_item(item, normalize_model)) is not None
                ]
                if models:
                    return models
    except Exception:
        pass
    return []


def parse_ollama_cli_line(line: str, normalize_model: Callable[..., NormalizedModelInfo]) -> NormalizedModelInfo | None:
    parts = [p for p in line.strip().split() if p]
    if not parts:
        return None
    model_id = parts[0]
    size = parts[2] if len(parts) >= 3 else None
    return normalize_model(
        model_id=model_id,
        installed=True,
        downloadable=True,
        size=size,
    )


async def ollama_cli_list(normalize_model: Callable[..., NormalizedModelInfo]) -> List[NormalizedModelInfo]:
    if shutil.which("ollama") is None:
        return []
    try:
        proc = await asyncio.create_subprocess_exec(
            "ollama",
            "list",
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        stdout, _stderr = await proc.communicate()
        if proc.returncode == 0:
            lines = stdout.decode("utf-8", errors="ignore").splitlines()
            models = [
                m for idx, line in enumerate(lines)
                if not (idx == 0 and "NAME" in line.upper()) and (m := parse_ollama_cli_line(line, normalize_model)) is not None
            ]
            if models:
                return models
    except Exception:
        pass
    return []


async def ollama_list_installed(normalize_model: Callable[..., NormalizedModelInfo]) -> List[NormalizedModelInfo]:
    models = await ollama_api_list(normalize_model)
    if models:
        return models
    models = await ollama_cli_list(normalize_model)
    if models:
        return models
    return ollama_list_from_disk(normalize_model)


async def ollama_health() -> bool:
    try:
        async with httpx.AsyncClient(timeout=5) as client:
            resp = await client.get("http://localhost:11434/api/tags")
            return 200 <= resp.status_code < 300
    except Exception:
        return False


async def ensure_ollama_ready() -> bool:
    if await ollama_health():
        return True

    if shutil.which("ollama") is None:
        return False

    try:
        await asyncio.create_subprocess_exec(
            "ollama",
            "serve",
            stdout=asyncio.subprocess.DEVNULL,
            stderr=asyncio.subprocess.DEVNULL,
            creationflags=subprocess.CREATE_NO_WINDOW if sys.platform == "win32" else 0,
        )
        for _ in range(30):
            await asyncio.sleep(1.0)
            if await ollama_health():
                return True
        return False
    except Exception:
        return False
