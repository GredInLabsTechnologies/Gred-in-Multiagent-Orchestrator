"""Tests for ModelRecommendationEngine — hardware-aware GGUF scoring."""

from __future__ import annotations

from dataclasses import dataclass

import pytest

from tools.gimo_server.services.mesh.model_recommendation import (
    FitLevel,
    ModelRecommendation,
    recommend_models,
    score_model,
    _parse_params_b,
)


@dataclass
class FakeModel:
    model_id: str
    params: str
    quantization: str
    size_bytes: int


class TestParseParams:
    def test_3b(self):
        assert _parse_params_b("3b") == 3.0

    def test_0_5b(self):
        assert _parse_params_b("0.5b") == 0.5

    def test_7B_caps(self):
        assert _parse_params_b("7B") == 7.0

    def test_500m(self):
        assert _parse_params_b("500m") == 0.5

    def test_empty(self):
        assert _parse_params_b("") == 0.0


class TestScoreModel:
    """Galaxy S10: Exynos 9820, 6GB RAM, ~20GB free storage."""

    def test_small_model_on_s10_is_optimal(self):
        rec = score_model(
            model_id="qwen2.5_0.5b_q4_k_m",
            params_str="0.5b", quant_str="q4_k_m",
            size_bytes=400 * 1024 * 1024,  # 400MB
            ram_total_mb=6144, storage_free_mb=20480,
            cpu_cores=8, soc_model="Exynos 9820",
        )
        assert rec.fit_level == FitLevel.optimal
        assert rec.estimated_ram_gb < 1.0
        assert rec.estimated_tokens_per_sec > 10
        assert rec.warnings == []

    def test_3b_model_on_s10_is_comfortable(self):
        rec = score_model(
            model_id="qwen2.5_3b_q4_k_m",
            params_str="3b", quant_str="q4_k_m",
            size_bytes=2 * 1024 * 1024 * 1024,  # 2GB
            ram_total_mb=6144, storage_free_mb=20480,
            cpu_cores=8, soc_model="Exynos 9820",
        )
        assert rec.fit_level in (FitLevel.optimal, FitLevel.comfortable)
        assert rec.estimated_ram_gb > 1.0

    def test_7b_model_on_s10_is_tight_or_overload(self):
        rec = score_model(
            model_id="llama3_7b_q4_k_m",
            params_str="7b", quant_str="q4_k_m",
            size_bytes=4 * 1024 * 1024 * 1024,  # 4GB
            ram_total_mb=6144, storage_free_mb=20480,
            cpu_cores=8, soc_model="Exynos 9820",
        )
        assert rec.fit_level in (FitLevel.tight, FitLevel.overload)
        assert len(rec.warnings) > 0

    def test_13b_model_overloads_s10(self):
        rec = score_model(
            model_id="llama3_13b_q4_k_m",
            params_str="13b", quant_str="q4_k_m",
            size_bytes=7 * 1024 * 1024 * 1024,  # 7GB
            ram_total_mb=6144, storage_free_mb=20480,
            cpu_cores=8, soc_model="Exynos 9820",
        )
        assert rec.fit_level == FitLevel.overload
        assert "Run at your own risk" in rec.impact
        assert rec.recommended_mode == "utility"

    def test_storage_insufficient(self):
        rec = score_model(
            model_id="big_model",
            params_str="3b", quant_str="q4_k_m",
            size_bytes=15 * 1024 * 1024 * 1024,  # 15GB
            ram_total_mb=6144, storage_free_mb=10240,  # 10GB free
            cpu_cores=4, soc_model="Exynos 9820",
        )
        assert any("Insufficient storage" in w for w in rec.warnings)

    def test_flagship_device_handles_7b(self):
        """Snapdragon 8 Gen 3 + 12GB RAM should handle 7B comfortably."""
        rec = score_model(
            model_id="qwen2.5_7b_q4_k_m",
            params_str="7b", quant_str="q4_k_m",
            size_bytes=4 * 1024 * 1024 * 1024,
            ram_total_mb=12288, storage_free_mb=50000,
            cpu_cores=8, soc_model="Snapdragon 8 Gen 3",
            has_gpu_compute=True,
        )
        assert rec.fit_level in (FitLevel.optimal, FitLevel.comfortable)
        assert rec.estimated_tokens_per_sec > 10

    def test_mode_recommendation(self):
        # Tight → hybrid
        rec_tight = score_model(
            model_id="m", params_str="7b", quant_str="q4_k_m",
            size_bytes=4_000_000_000, ram_total_mb=6144,
            storage_free_mb=20480, soc_model="Exynos 9820",
        )
        if rec_tight.fit_level == FitLevel.tight:
            assert rec_tight.recommended_mode == "hybrid"

        # Overload → utility
        rec_over = score_model(
            model_id="m", params_str="13b", quant_str="q4_k_m",
            size_bytes=7_000_000_000, ram_total_mb=4096,
            storage_free_mb=20480, soc_model="unknown",
        )
        assert rec_over.recommended_mode == "utility"

    def test_to_dict(self):
        rec = score_model(
            model_id="test", params_str="3b", quant_str="q4_k_m",
            size_bytes=2_000_000_000, ram_total_mb=8192,
            storage_free_mb=20480, soc_model="Exynos 9820",
        )
        d = rec.to_dict()
        assert "fit_level" in d
        assert "score" in d
        assert "impact" in d
        assert "warnings" in d
        assert "recommended_mode" in d


class TestRecommendModels:
    def _make_models(self):
        return [
            FakeModel("small_0.5b_q4", "0.5b", "q4_k_m", 400_000_000),
            FakeModel("medium_3b_q4", "3b", "q4_k_m", 2_000_000_000),
            FakeModel("large_7b_q4", "7b", "q4_k_m", 4_000_000_000),
            FakeModel("huge_13b_q4", "13b", "q4_k_m", 7_500_000_000),
        ]

    def test_recommends_best_fit(self):
        recs = recommend_models(
            models=self._make_models(),
            ram_total_mb=6144, storage_free_mb=20480,
            cpu_cores=8, soc_model="Exynos 9820",
        )
        recommended = [r for r in recs if r.recommended]
        assert len(recommended) == 1
        # Should NOT recommend 13b on 6GB device
        assert recommended[0].model_id != "huge_13b_q4"

    def test_sorted_by_score(self):
        recs = recommend_models(
            models=self._make_models(),
            ram_total_mb=6144, storage_free_mb=20480,
            cpu_cores=8, soc_model="Exynos 9820",
        )
        scores = [r.score for r in recs]
        assert scores == sorted(scores, reverse=True)

    def test_all_overload_still_recommends(self):
        """Even if all models overload, recommend the least bad one."""
        recs = recommend_models(
            models=self._make_models(),
            ram_total_mb=1024,  # 1GB RAM — everything overloads
            storage_free_mb=20480,
            cpu_cores=2, soc_model="unknown",
        )
        recommended = [r for r in recs if r.recommended]
        assert len(recommended) == 1
        assert "utility" in recommended[0].recommendation_reason.lower() or \
               "no model" in recommended[0].recommendation_reason.lower()

    def test_flagship_recommends_bigger_model(self):
        recs = recommend_models(
            models=self._make_models(),
            ram_total_mb=12288, storage_free_mb=50000,
            cpu_cores=8, soc_model="Snapdragon 8 Gen 3",
            has_gpu_compute=True,
        )
        recommended = [r for r in recs if r.recommended]
        assert len(recommended) == 1
        # Flagship should recommend 3b or 7b, not 0.5b
        assert recommended[0].model_id in ("medium_3b_q4", "large_7b_q4")

    def test_recommendation_has_reason(self):
        recs = recommend_models(
            models=self._make_models(),
            ram_total_mb=6144, storage_free_mb=20480,
            cpu_cores=8, soc_model="Exynos 9820",
        )
        recommended = [r for r in recs if r.recommended][0]
        assert recommended.recommendation_reason != ""
        assert "tok/s" in recommended.recommendation_reason
