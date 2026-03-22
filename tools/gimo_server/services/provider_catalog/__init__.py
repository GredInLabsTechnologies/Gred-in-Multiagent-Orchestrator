"""Provider catalog service package.

Re-exports ProviderCatalogService for backward compatibility:
    from tools.gimo_server.services.provider_catalog import ProviderCatalogService
"""
from .service import ProviderCatalogService

__all__ = ["ProviderCatalogService"]
