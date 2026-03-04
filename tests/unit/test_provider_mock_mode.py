import pytest

from tools.gimo_server.ops_models import ProviderValidateRequest
from tools.gimo_server.providers.openai_compat import OpenAICompatAdapter
from tools.gimo_server.services.provider_catalog_service import ProviderCatalogService


@pytest.mark.asyncio
async def test_openai_compat_adapter_mock_generate_and_health(monkeypatch):
    monkeypatch.setenv("ORCH_PROVIDER_MOCK_MODE", "1")
    adapter = OpenAICompatAdapter(base_url="https://api.openai.com/v1", model="gpt-4o", api_key=None)

    out = await adapter.generate("hola mundo", {"model": "gpt-4o-mini"})
    assert "[MOCK:gpt-4o-mini]" in out["content"]
    assert out["usage"]["prompt_tokens"] > 0
    assert await adapter.health_check() is True


@pytest.mark.asyncio
async def test_provider_catalog_validate_credentials_mock_mode(monkeypatch):
    monkeypatch.delenv("ORCH_PROVIDER_MOCK_MODE", raising=False)

    payload = ProviderValidateRequest(api_key="mock:anything")
    resp = await ProviderCatalogService.validate_credentials("azure-openai", payload)

    assert resp.valid is True
    assert resp.health == "ok"
    assert resp.effective_model is not None
    assert any("Mock mode enabled" in w for w in resp.warnings)


@pytest.mark.asyncio
async def test_provider_catalog_list_available_models_mock_mode_synthetic(monkeypatch):
    monkeypatch.delenv("ORCH_PROVIDER_MOCK_MODE", raising=False)

    payload = ProviderValidateRequest(api_key="mock:test")
    models, warnings = await ProviderCatalogService.list_available_models("custom_openai_compatible", payload=payload)

    assert len(models) == 1
    assert models[0].id == "custom_openai_compatible-mock-model"
    assert any("Mock mode enabled" in w for w in warnings)
