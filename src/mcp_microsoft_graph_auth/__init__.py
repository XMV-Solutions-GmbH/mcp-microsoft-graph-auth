# SPDX-License-Identifier: MIT OR Apache-2.0
# SPDX-FileCopyrightText: 2026 XMV Solutions GmbH
# SPDX-FileContributor: David Koller <david.koller@xmv.de>
"""Shared Microsoft Graph auth helpers for MCP servers.

Public API (v0.0.x — stabilising; expect occasional breaking changes
until v0.1.0). Currently:

- `tokens.CachedToken` — persisted-token value type.
- `device_code.request_device_code` / `poll_for_token` /
  `refresh_access_token` — OAuth Device Code primitives.

Pending modules (see issue tracker):

- `token_store` — pluggable storage backends (#3).
- `service_principal` — client-credentials grant (#4).
- `login_session` — `LoginSession` + `LoginSessionRegistry` for
  MCP-tool-driven login flows (#5).

Compatibility: Python 3.11+. The library is prefix-agnostic — it
does not read environment variables on its own. Each consumer reads
its own env-var conventions and passes values explicitly to the
primitives.
"""

from __future__ import annotations

from .device_code import (
    AUTHORITY_BASE,
    AuthorizationDeniedError,
    DeviceCodeChallenge,
    DeviceCodeError,
    DeviceCodeExpiredError,
    RefreshTokenInvalidError,
    poll_for_token,
    refresh_access_token,
    request_device_code,
)
from .tokens import DEFAULT_REFRESH_BUFFER_SECONDS, CachedToken

__version__ = "0.0.1.dev0"

__all__ = [
    "AUTHORITY_BASE",
    "DEFAULT_REFRESH_BUFFER_SECONDS",
    "AuthorizationDeniedError",
    "CachedToken",
    "DeviceCodeChallenge",
    "DeviceCodeError",
    "DeviceCodeExpiredError",
    "RefreshTokenInvalidError",
    "__version__",
    "poll_for_token",
    "refresh_access_token",
    "request_device_code",
]
