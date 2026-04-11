"""Unit tests for ModelCatalogService — GGUF model scanning and metadata."""

from __future__ import annotations

import hashlib
import shutil
import tempfile
from pathlib import Path
from typing import Generator

import pytest

from tools.gimo_server.services.mesh import model_catalog as catalog_mod
from tools.gimo_server.services.mesh.model_catalog import ModelCatalogService, ModelInfo


@pytest.fixture()
def models_dir(monkeypatch: pytest.MonkeyPatch) -> Generator[Path, None, None]:
    d = Path(tempfile.mkdtemp(prefix="model_catalog_test_"))
    models = d / "mesh" / "models"
    models.mkdir(parents=True)
    monkeypatch.setattr(catalog_mod, "_MODELS_DIR", models)
    yield models
    shutil.rmtree(d, ignore_errors=True)


@pytest.fixture()
def svc(models_dir: Path) -> ModelCatalogService:
    return ModelCatalogService()


def _write_fake_gguf(models_dir: Path, name: str, size: int = 1024) -> Path:
    """Write a fake GGUF file with deterministic content."""
    path = models_dir / name
    path.write_bytes(b"x" * size)
    return path


def _sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


# ═══════════════════════════════════════════════════════════════
# Listing
# ═══════════════════════════════════════════════════════════════

class TestListModels:
    def test_empty_dir(self, svc: ModelCatalogService):
        assert svc.list_models() == []

    def test_single_model(self, svc: ModelCatalogService, models_dir: Path):
        _write_fake_gguf(models_dir, "qwen2.5_3b_q4_k_m.gguf")
        models = svc.list_models()
        assert len(models) == 1

    def test_multiple_models(self, svc: ModelCatalogService, models_dir: Path):
        _write_fake_gguf(models_dir, "model_a.gguf")
        _write_fake_gguf(models_dir, "model_b.gguf")
        _write_fake_gguf(models_dir, "model_c.gguf")
        assert len(svc.list_models()) == 3

    def test_ignores_non_gguf(self, svc: ModelCatalogService, models_dir: Path):
        _write_fake_gguf(models_dir, "model.gguf")
        (models_dir / "readme.txt").write_text("not a model")
        (models_dir / "data.bin").write_bytes(b"binary")
        assert len(svc.list_models()) == 1

    def test_sorted_by_name(self, svc: ModelCatalogService, models_dir: Path):
        _write_fake_gguf(models_dir, "zebra.gguf")
        _write_fake_gguf(models_dir, "alpha.gguf")
        models = svc.list_models()
        assert models[0].filename == "alpha.gguf"
        assert models[1].filename == "zebra.gguf"


# ═══════════════════════════════════════════════════════════════
# Metadata parsing
# ═══════════════════════════════════════════════════════════════

class TestMetadataParsing:
    def test_model_id_from_filename(self, svc: ModelCatalogService, models_dir: Path):
        _write_fake_gguf(models_dir, "qwen2.5_3b_q4_k_m.gguf")
        m = svc.list_models()[0]
        assert m.model_id == "qwen2.5_3b_q4_k_m"

    def test_filename_preserved(self, svc: ModelCatalogService, models_dir: Path):
        _write_fake_gguf(models_dir, "my-model.gguf")
        m = svc.list_models()[0]
        assert m.filename == "my-model.gguf"

    def test_size_bytes(self, svc: ModelCatalogService, models_dir: Path):
        _write_fake_gguf(models_dir, "model.gguf", size=4096)
        m = svc.list_models()[0]
        assert m.size_bytes == 4096

    def test_sha256_computed(self, svc: ModelCatalogService, models_dir: Path):
        content = b"deterministic content for hash"
        (models_dir / "model.gguf").write_bytes(content)
        m = svc.list_models()[0]
        assert m.sha256 == _sha256(content)

    def test_fallback_name_for_simple_filename(self, svc: ModelCatalogService, models_dir: Path):
        _write_fake_gguf(models_dir, "simple-model.gguf")
        m = svc.list_models()[0]
        # Should use filename without .gguf as name
        assert "simple-model" in m.name.lower() or m.name == "simple-model"


# ═══════════════════════════════════════════════════════════════
# Lookup
# ═══════════════════════════════════════════════════════════════

class TestLookup:
    def test_get_model_found(self, svc: ModelCatalogService, models_dir: Path):
        _write_fake_gguf(models_dir, "target.gguf")
        m = svc.get_model("target")
        assert m is not None
        assert m.model_id == "target"

    def test_get_model_not_found(self, svc: ModelCatalogService, models_dir: Path):
        _write_fake_gguf(models_dir, "other.gguf")
        assert svc.get_model("nonexistent") is None

    def test_get_model_path_found(self, svc: ModelCatalogService, models_dir: Path):
        _write_fake_gguf(models_dir, "target.gguf")
        path = svc.get_model_path("target")
        assert path is not None
        assert path.exists()
        assert path.name == "target.gguf"

    def test_get_model_path_not_found(self, svc: ModelCatalogService):
        assert svc.get_model_path("ghost") is None


# ═══════════════════════════════════════════════════════════════
# Caching
# ═══════════════════════════════════════════════════════════════

class TestCaching:
    def test_cache_hit_on_same_size(self, svc: ModelCatalogService, models_dir: Path):
        _write_fake_gguf(models_dir, "cached.gguf", size=2048)
        m1 = svc.list_models()[0]
        m2 = svc.list_models()[0]
        # Same object from cache (sha256 won't be recomputed)
        assert m1.sha256 == m2.sha256

    def test_cache_invalidated_on_size_change(self, svc: ModelCatalogService, models_dir: Path):
        path = _write_fake_gguf(models_dir, "changing.gguf", size=1024)
        m1 = svc.list_models()[0]
        assert m1.size_bytes == 1024

        # Overwrite with different size
        path.write_bytes(b"y" * 2048)
        m2 = svc.list_models()[0]
        assert m2.size_bytes == 2048
        assert m2.sha256 == _sha256(b"y" * 2048)
