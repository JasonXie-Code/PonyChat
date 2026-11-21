from __future__ import annotations

from Backend import config
from Backend.providers.llm_call import _get_default_httpx_client


class _OpenClient:
    is_closed = False


class _ClosedClient:
    is_closed = True


def test_default_llm_client_reuses_lifespan_connection_pool(monkeypatch):
    shared = _OpenClient()
    monkeypatch.setattr(config, "httpx_client", shared)

    assert _get_default_httpx_client() is shared
    assert _get_default_httpx_client() is shared


def test_default_llm_client_does_not_reuse_closed_pool(monkeypatch):
    monkeypatch.setattr(config, "httpx_client", _ClosedClient())

    assert _get_default_httpx_client() is None
