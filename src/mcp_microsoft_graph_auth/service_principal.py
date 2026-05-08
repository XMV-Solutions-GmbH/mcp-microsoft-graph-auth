# SPDX-License-Identifier: MIT OR Apache-2.0
# SPDX-FileCopyrightText: 2026 XMV Solutions GmbH
# SPDX-FileContributor: David Koller <david.koller@xmv.de>
"""Service-principal / client-credentials grant.

For unattended automation: CI runners, scheduled jobs, multi-tenant
onboarding scripts. Trades human-attribution-in-the-audit-log for
the ability to run without a signed-in user.

**Audit trail caveat.** App-only tokens attribute every action in
the consuming Microsoft Graph service's audit log to the
*application* principal, NOT a real user. The compliance-friendly
default for end-user-facing MCP servers is delegated user auth
(Device Code). Switch to service-principal only when no human is in
the loop.

The app registration that backs this flow MUST be granted
*Application* (not just Delegated) Microsoft Graph permissions
appropriate to the consuming service (e.g. `Files.ReadWrite.All`
for SharePoint, `Mail.ReadWrite` for Outlook). Admin consent must
be recorded by a tenant admin. Microsoft's `/v2.0/.default` scope
syntax tells AAD "issue a token covering exactly the application
permissions already consented".

**Prefix-agnostic API.** Unlike sharepoint-mcp's predecessor of
this module, no env-var reading happens here. `acquire_app_only_token`
takes explicit `client_id` / `client_secret` / `tenant` args. The
in-process token cache is exposed as a `AppOnlyTokenCache` class
that the consumer instantiates and threads through; consumers' env-
var-driven dispatch (e.g. detecting `SP_AUTH_MODE=service-principal`)
stays in the consumer.
"""

from __future__ import annotations

import threading
import time

import httpx

from .device_code import AUTHORITY_BASE
from .tokens import CachedToken

SERVICE_PRINCIPAL_SCOPE = "https://graph.microsoft.com/.default"


def acquire_app_only_token(
    *,
    client_id: str,
    client_secret: str,
    tenant: str,
    http: httpx.Client | None = None,
) -> CachedToken:
    """Client-credentials grant. Returns CachedToken (no refresh_token).

    Per Microsoft's v2.0 `/.default` semantics, the scope is fixed —
    AAD issues a token covering whatever Application permissions the
    tenant admin has consented to.

    `tenant` must be a real tenant GUID or domain (not the
    `"organizations"` multi-tenant authority used for delegated
    flows — client-credentials requires a specific tenant context).
    """
    client = http if http is not None else httpx.Client(timeout=10.0)
    request_started = time.time()
    try:
        response = client.post(
            f"{AUTHORITY_BASE}/{tenant}/oauth2/v2.0/token",
            data={
                "grant_type": "client_credentials",
                "client_id": client_id,
                "client_secret": client_secret,
                "scope": SERVICE_PRINCIPAL_SCOPE,
            },
        )
        response.raise_for_status()
        payload = response.json()
    finally:
        if http is None:
            client.close()
    return CachedToken(
        access_token=str(payload["access_token"]),
        refresh_token=None,
        expires_at=request_started + float(payload.get("expires_in", 0)),
        scope=str(payload.get("scope", "")),
    )


class AppOnlyTokenCache:
    """In-process cache of app-only access tokens, keyed by (client_id, tenant).

    Tokens are NOT persisted to disk — the client secret is already
    in env vars (typically rotated externally), and a persisted
    app-only token adds attack surface without much value (acquisition
    is sub-second once the secret is correct).

    Thread-safe: a single lock serialises read-modify-write. The
    network round-trip happens **outside** the lock so other callers
    aren't blocked on a slow Microsoft Identity response. If two
    callers race for an empty key, both acquire fresh tokens
    independently — wasteful but correct.

    Each consumer typically instantiates one of these for its
    process lifetime; multiple consumers in one Python process can
    share an instance or use independent ones (the cache key
    naturally scopes by client_id, so independent instances rarely
    conflict).
    """

    def __init__(self) -> None:
        self._cache: dict[tuple[str, str], CachedToken] = {}
        self._lock = threading.Lock()

    def get_or_acquire(
        self,
        *,
        client_id: str,
        client_secret: str,
        tenant: str,
        http: httpx.Client | None = None,
    ) -> str:
        """Return a valid app-only access-token string for (client_id, tenant)."""
        if not client_id or not client_secret or not tenant:
            raise ValueError(
                "AppOnlyTokenCache.get_or_acquire requires non-empty client_id, "
                "client_secret, and tenant",
            )
        key = (client_id, tenant)
        with self._lock:
            cached = self._cache.get(key)
            if cached is not None and not cached.is_expired():
                return cached.access_token
        # Acquire new outside the lock — see class docstring.
        new = acquire_app_only_token(
            client_id=client_id,
            client_secret=client_secret,
            tenant=tenant,
            http=http,
        )
        with self._lock:
            self._cache[key] = new
        return new.access_token

    def reset(self) -> None:
        """Drop all cached entries. Useful for tests + secret-rotation flows."""
        with self._lock:
            self._cache.clear()
