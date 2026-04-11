from tools.gimo_server.services.providers.capability_service import ProviderCapabilityService


def test_normalize_provider_type_accepts_cloudflare_workers_ai_aliases() -> None:
    assert ProviderCapabilityService.normalize_provider_type("cloudflare") == "cloudflare-workers-ai"
    assert ProviderCapabilityService.normalize_provider_type("workers-ai") == "cloudflare-workers-ai"
    assert ProviderCapabilityService.normalize_provider_type("cloudflare_workers_ai") == "cloudflare-workers-ai"


def test_capabilities_for_cloudflare_workers_ai_are_remote_api_key_only() -> None:
    caps = ProviderCapabilityService.capabilities_for("cloudflare-workers-ai")

    assert caps["auth_modes_supported"] == ["api_key"]
    assert caps["requires_remote_api"] is True
    assert caps["supports_account_mode"] is False
    assert caps["supports_recommended_models"] is True
