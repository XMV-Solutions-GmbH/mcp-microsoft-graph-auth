# SPDX-License-Identifier: MIT OR Apache-2.0
# SPDX-FileCopyrightText: 2026 XMV Solutions GmbH
# SPDX-FileContributor: David Koller <david.koller@xmv.de>
"""Unit tests for the service-principal / client-credentials primitive
and the in-process token cache.

The env-var-driven dispatcher (`is_service_principal_mode` /
`get_app_only_token`) lives in the consumer (sharepoint-mcp,
outlook-mcp), not here. Those tests stay in the consumer's repo.
"""

from __future__ import annotations

import time

import httpx
import pytest
import respx

from mcp_microsoft_graph_auth.device_code import AUTHORITY_BASE
from mcp_microsoft_graph_auth.service_principal import (
    SERVICE_PRINCIPAL_SCOPE,
    AppOnlyTokenCache,
    acquire_app_only_token,
)
from mcp_microsoft_graph_auth.tokens import CachedToken

# ---------------------------------------------------------------------
# acquire_app_only_token — wire shape
# ---------------------------------------------------------------------


@respx.mock
def test_acquire_app_only_token_uses_client_credentials_grant() -> None:
    tenant = "tenant-guid"
    route = respx.post(f"{AUTHORITY_BASE}/{tenant}/oauth2/v2.0/token").respond(
        json={
            "token_type": "Bearer",
            "expires_in": 3599,
            "access_token": "AT-app",
            "scope": "https://graph.microsoft.com/.default",
        }
    )
    cached = acquire_app_only_token(client_id="cid", client_secret="secret", tenant=tenant)
    assert cached.access_token == "AT-app"
    assert cached.refresh_token is None
    body = route.calls.last.request.read().decode()
    assert "grant_type=client_credentials" in body
    assert "client_id=cid" in body
    assert "client_secret=secret" in body
    assert "scope=https" in body  # SERVICE_PRINCIPAL_SCOPE


@respx.mock
def test_acquire_app_only_token_propagates_4xx() -> None:
    tenant = "t"
    respx.post(f"{AUTHORITY_BASE}/{tenant}/oauth2/v2.0/token").respond(
        401, json={"error": "invalid_client"}
    )
    with pytest.raises(httpx.HTTPStatusError):
        acquire_app_only_token(client_id="cid", client_secret="bad", tenant=tenant)


def test_service_principal_scope_is_dot_default() -> None:
    """The /.default suffix is what tells AAD to issue a token covering all
    consented Application permissions. Don't change this without a code search."""
    assert SERVICE_PRINCIPAL_SCOPE == "https://graph.microsoft.com/.default"


# ---------------------------------------------------------------------
# AppOnlyTokenCache — caching, refresh-on-expiry, multi-tenant isolation
# ---------------------------------------------------------------------


@respx.mock
def test_cache_caches_until_expiry() -> None:
    cache = AppOnlyTokenCache()
    route = respx.post(f"{AUTHORITY_BASE}/t/oauth2/v2.0/token").respond(
        json={"access_token": "AT-1", "expires_in": 3600, "scope": ""},
    )
    assert cache.get_or_acquire(client_id="c", client_secret="s", tenant="t") == "AT-1"
    assert cache.get_or_acquire(client_id="c", client_secret="s", tenant="t") == "AT-1"
    assert cache.get_or_acquire(client_id="c", client_secret="s", tenant="t") == "AT-1"
    assert route.call_count == 1


@respx.mock
def test_cache_reacquires_after_expiry() -> None:
    cache = AppOnlyTokenCache()
    route = respx.post(f"{AUTHORITY_BASE}/t/oauth2/v2.0/token").mock(
        side_effect=[
            httpx.Response(200, json={"access_token": "AT-old", "expires_in": -60, "scope": ""}),
            httpx.Response(200, json={"access_token": "AT-new", "expires_in": 3600, "scope": ""}),
        ],
    )
    first = cache.get_or_acquire(client_id="c", client_secret="s", tenant="t")
    second = cache.get_or_acquire(client_id="c", client_secret="s", tenant="t")
    assert first == "AT-old"
    assert second == "AT-new"
    assert route.call_count == 2


@respx.mock
def test_cache_separate_per_tenant() -> None:
    """Two distinct (client_id, tenant) pairs cache separately."""
    cache = AppOnlyTokenCache()
    respx.post(f"{AUTHORITY_BASE}/t1/oauth2/v2.0/token").respond(
        json={"access_token": "AT-T1", "expires_in": 3600, "scope": ""},
    )
    respx.post(f"{AUTHORITY_BASE}/t2/oauth2/v2.0/token").respond(
        json={"access_token": "AT-T2", "expires_in": 3600, "scope": ""},
    )
    assert cache.get_or_acquire(client_id="c", client_secret="s", tenant="t1") == "AT-T1"
    assert cache.get_or_acquire(client_id="c", client_secret="s", tenant="t2") == "AT-T2"
    # Re-call for t1 hits cache, doesn't acquire again
    assert cache.get_or_acquire(client_id="c", client_secret="s", tenant="t1") == "AT-T1"


@respx.mock
def test_cache_separate_per_client_id() -> None:
    """Different client_id, same tenant — different cache entries."""
    cache = AppOnlyTokenCache()
    respx.post(f"{AUTHORITY_BASE}/t/oauth2/v2.0/token").mock(
        side_effect=[
            httpx.Response(200, json={"access_token": "AT-A", "expires_in": 3600, "scope": ""}),
            httpx.Response(200, json={"access_token": "AT-B", "expires_in": 3600, "scope": ""}),
        ],
    )
    assert cache.get_or_acquire(client_id="cid-A", client_secret="s", tenant="t") == "AT-A"
    assert cache.get_or_acquire(client_id="cid-B", client_secret="s", tenant="t") == "AT-B"


def test_cache_reset_clears_entries() -> None:
    cache = AppOnlyTokenCache()
    cache._cache[("c", "t")] = CachedToken(
        access_token="x",
        refresh_token=None,
        expires_at=time.time() + 1000,
        scope="",
    )
    assert cache._cache  # populated
    cache.reset()
    assert cache._cache == {}


def test_cache_rejects_empty_args() -> None:
    cache = AppOnlyTokenCache()
    with pytest.raises(ValueError, match="non-empty"):
        cache.get_or_acquire(client_id="", client_secret="s", tenant="t")
    with pytest.raises(ValueError, match="non-empty"):
        cache.get_or_acquire(client_id="c", client_secret="", tenant="t")
    with pytest.raises(ValueError, match="non-empty"):
        cache.get_or_acquire(client_id="c", client_secret="s", tenant="")


@respx.mock
def test_two_caches_are_independent() -> None:
    """Each AppOnlyTokenCache instance is a fresh dict — no global state."""
    respx.post(f"{AUTHORITY_BASE}/t/oauth2/v2.0/token").mock(
        side_effect=[
            httpx.Response(200, json={"access_token": "AT-X", "expires_in": 3600, "scope": ""}),
            httpx.Response(200, json={"access_token": "AT-Y", "expires_in": 3600, "scope": ""}),
        ],
    )
    cache_a = AppOnlyTokenCache()
    cache_b = AppOnlyTokenCache()
    # cache_a populates entry for (c, t)
    assert cache_a.get_or_acquire(client_id="c", client_secret="s", tenant="t") == "AT-X"
    # cache_b doesn't see a's entry — fresh acquisition
    assert cache_b.get_or_acquire(client_id="c", client_secret="s", tenant="t") == "AT-Y"
