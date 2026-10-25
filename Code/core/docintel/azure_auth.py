"""One shared Azure credential per process (managed identity on App Service, developer login locally)."""

from __future__ import annotations

from functools import lru_cache

from .config import get_settings


@lru_cache(maxsize=1)
def get_credential():
    from azure.identity import DefaultAzureCredential

    client_id = get_settings().azure_client_id
    return DefaultAzureCredential(managed_identity_client_id=client_id or None,
                                  exclude_interactive_browser_credential=True)
