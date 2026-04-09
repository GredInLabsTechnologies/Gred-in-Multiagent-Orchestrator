import pytest
import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch
from tools.gimo_server.services.providers.service import ProviderService

# ── Phase 6 Provider Strategy ─────────────────────────────


@pytest.mark.asyncio
async def test_phase6_provider_strategy_no_fallback_on_policy_error():
    with patch.object(ProviderService, "static_generate", new_callable=AsyncMock) as mock_generate:
        mock_generate.side_effect = RuntimeError("policy check failed")
        with pytest.raises(RuntimeError) as exc:
            await ProviderService.static_generate_phase6_strategy(
                prompt="hola",
                context={},
                intent_effective="SAFE_REFACTOR",
                path_scope=["tools/gimo_server/services/ops_service.py"],
            )
        assert "PHASE6_NO_FALLBACK" in str(exc.value)


@pytest.mark.asyncio
async def test_phase6_provider_strategy_no_fallback_on_schema_error():
    with patch.object(ProviderService, "static_generate", new_callable=AsyncMock) as mock_generate:
        mock_generate.side_effect = RuntimeError("schema validation failed")
        with pytest.raises(RuntimeError) as exc:
            await ProviderService.static_generate_phase6_strategy(
                prompt="hola",
                context={},
                intent_effective="SAFE_REFACTOR",
                path_scope=["tools/gimo_server/services/ops_service.py"],
            )
        assert "PHASE6_NO_FALLBACK" in str(exc.value)


@pytest.mark.asyncio
async def test_phase6_provider_strategy_no_fallback_on_merge_gate_error():
    with patch.object(ProviderService, "static_generate", new_callable=AsyncMock) as mock_generate:
        mock_generate.side_effect = RuntimeError("merge gate failed")
        with pytest.raises(RuntimeError) as exc:
            await ProviderService.static_generate_phase6_strategy(
                prompt="hola",
                context={},
                intent_effective="SAFE_REFACTOR",
                path_scope=["tools/gimo_server/services/ops_service.py"],
            )
        assert "PHASE6_NO_FALLBACK" in str(exc.value)


@pytest.mark.asyncio
async def test_phase6_provider_strategy_fallback_on_429():
    with patch.object(ProviderService, "static_generate", new_callable=AsyncMock) as mock_generate:
        import httpx

        req = httpx.Request("POST", "http://localhost/v1/chat/completions")
        resp = httpx.Response(429, request=req)
        mock_generate.side_effect = [
            httpx.HTTPStatusError("too many requests", request=req, response=resp),
            httpx.HTTPStatusError("too many requests", request=req, response=resp),
            {"provider": "local_ollama", "model": "qwen3:8b", "content": "ok", "tokens_used": 1, "cost_usd": 0.0},
        ]

        result = await ProviderService.static_generate_phase6_strategy(
            prompt="hola",
            context={},
            intent_effective="SAFE_REFACTOR",
            path_scope=["tools/gimo_server/services/ops_service.py"],
        )

        assert result["fallback_used"] is True
        assert result["failure_reason"] == "429"
        assert result["execution_decision"] == "FALLBACK_MODEL_USED"
        assert isinstance(result["fallback_count_window"], int)


@pytest.mark.asyncio
async def test_phase6_provider_strategy_fallback_on_5xx():
    with patch.object(ProviderService, "static_generate", new_callable=AsyncMock) as mock_generate:
        import httpx

        req = httpx.Request("POST", "http://localhost/v1/chat/completions")
        resp = httpx.Response(503, request=req)
        mock_generate.side_effect = [
            httpx.HTTPStatusError("service unavailable", request=req, response=resp),
            httpx.HTTPStatusError("service unavailable", request=req, response=resp),
            {"provider": "local_ollama", "model": "qwen3:8b", "content": "ok", "tokens_used": 1, "cost_usd": 0.0},
        ]

        result = await ProviderService.static_generate_phase6_strategy(
            prompt="hola",
            context={},
            intent_effective="SAFE_REFACTOR",
            path_scope=["tools/gimo_server/services/ops_service.py"],
        )

        assert result["fallback_used"] is True
        assert result["failure_reason"] == "5xx"
        assert result["execution_decision"] == "FALLBACK_MODEL_USED"


# ── Provider Service Outcome Recording ────────────────────


@pytest.mark.asyncio
async def test_provider_service_static_generate_records_outcome_success():
    fake_cfg = SimpleNamespace(
        active="p1",
        providers={
            "p1": SimpleNamespace(model="gpt-4o-mini", provider_type="openai", type="openai")
        },
    )
    fake_economy = SimpleNamespace(cache_enabled=False, cache_ttl_hours=24)

    class _Adapter:
        model = "gpt-4o-mini"

        async def generate(self, prompt, context):
            await asyncio.sleep(0)
            return {
                "content": "ok",
                "usage": {"prompt_tokens": 10, "completion_tokens": 5},
            }

    with patch.object(ProviderService, "get_config", return_value=fake_cfg):
        with patch.object(ProviderService, "_build_adapter", return_value=_Adapter()):
            with patch("tools.gimo_server.services.ops_service.OpsService.get_config", return_value=SimpleNamespace(economy=fake_economy)):
                with patch("tools.gimo_server.services.ops_service.OpsService.record_model_outcome") as mock_record:
                    result = await ProviderService.static_generate("hola", {"task_type": "coding"})

    assert result["content"] == "ok"
    assert mock_record.call_count == 1
    kwargs = mock_record.call_args.kwargs
    assert kwargs["success"] is True
    assert kwargs["provider_type"] == "openai"
    assert kwargs["model_id"] == "gpt-4o-mini"
    assert kwargs["task_type"] == "coding"


@pytest.mark.asyncio
async def test_provider_service_static_generate_records_outcome_failure():
    fake_cfg = SimpleNamespace(
        active="p1",
        providers={
            "p1": SimpleNamespace(model="gpt-4o-mini", provider_type="openai", type="openai")
        },
    )
    fake_economy = SimpleNamespace(cache_enabled=False, cache_ttl_hours=24)

    class _Adapter:
        model = "gpt-4o-mini"

        async def generate(self, prompt, context):
            raise RuntimeError("boom")

    with patch.object(ProviderService, "get_config", return_value=fake_cfg):
        with patch.object(ProviderService, "_build_adapter", return_value=_Adapter()):
            with patch("tools.gimo_server.services.ops_service.OpsService.get_config", return_value=SimpleNamespace(economy=fake_economy)):
                with patch("tools.gimo_server.services.ops_service.OpsService.record_model_outcome") as mock_record:
                    with pytest.raises(RuntimeError):
                        await ProviderService.static_generate("hola", {"task_type": "coding"})

    assert mock_record.call_count == 1
    kwargs = mock_record.call_args.kwargs
    assert kwargs["success"] is False
    assert kwargs["provider_type"] == "openai"
    assert kwargs["model_id"] == "gpt-4o-mini"
    assert kwargs["task_type"] == "coding"
