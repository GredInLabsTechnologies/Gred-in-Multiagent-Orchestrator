from __future__ import annotations

from ._base import ProviderCatalogBase
from ._ollama import OllamaMixin
from ._openai_compat import OpenAICompatMixin
from ._cli_account import CliAccountMixin
from ._install import InstallMixin
from ._remote import RemoteFetchMixin


class ProviderCatalogService(
    OllamaMixin,
    OpenAICompatMixin,
    CliAccountMixin,
    InstallMixin,
    RemoteFetchMixin,
    ProviderCatalogBase,
):
    """Lleva el registro de proveedores LLM, modelos e integracion."""
