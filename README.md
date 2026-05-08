<!--
SPDX-License-Identifier: MIT OR Apache-2.0
SPDX-FileCopyrightText: 2026 XMV Solutions GmbH
SPDX-FileContributor: David Koller <david.koller@xmv.de>
-->

# mcp-microsoft-graph-auth

Shared Microsoft Graph authentication helpers for [MCP](https://modelcontextprotocol.io) servers.

[![PyPI version](https://img.shields.io/pypi/v/mcp-microsoft-graph-auth.svg)](https://pypi.org/project/mcp-microsoft-graph-auth/)
[![CI](https://github.com/XMV-Solutions-GmbH/mcp-microsoft-graph-auth/actions/workflows/ci.yml/badge.svg)](https://github.com/XMV-Solutions-GmbH/mcp-microsoft-graph-auth/actions/workflows/ci.yml)
[![Python](https://img.shields.io/pypi/pyversions/mcp-microsoft-graph-auth.svg)](https://pypi.org/project/mcp-microsoft-graph-auth/)
[![License: MIT OR Apache-2.0](https://img.shields.io/badge/License-MIT_OR_Apache--2.0-blue.svg)](LICENSE-MIT)

## Why this exists

[`mcp-server-sharepoint`](https://github.com/XMV-Solutions-GmbH/sharepoint-mcp) and [`mcp-server-outlook`](https://github.com/XMV-Solutions-GmbH/outlook-mcp) (and likely future siblings — Teams, OneDrive, …) all need the same auth machinery against Microsoft Graph: OAuth Device Code flow, token cache with sensible storage backends, optional service-principal mode, multi-profile support.

This library factors that machinery out so each MCP server adds only what's specific to its API surface (scopes + tool names), not yet another reimplementation of Device Code + token storage.

## What's in the box

- **`device_code`** — primitives for the OAuth 2.0 Device Code flow against Microsoft Identity v2.0 (`request_device_code`, `poll_for_token`, `refresh_access_token`).
- **`service_principal`** — client-credentials grant for unattended automation (CI runners, scheduled jobs).
- **`token_store`** — three pluggable storage backends:
  - **OS keyring** (macOS Keychain / Windows Credential Locker / Linux Secret Service) when available.
  - **Plain file** mode 0600 (`~/.cache/<your-app>/<profile>/token.json`) — same convention as `gh auth`, `aws configure`.
  - **Encrypted file** with passphrase (Fernet + Scrypt KDF) for paranoid setups or shared CI cache.
- **`tokens`** — `CachedToken` dataclass with sensible JSON serialisation.
- **`login_session`** — `LoginSession` + `LoginSessionRegistry` for MCP-tool-driven login flows (the in-process state your `*_login_begin` / `*_login_status` tools share).

## Public API contract

The library is **prefix-agnostic**: it does not read environment variables on its own. Each consumer (an MCP server) is responsible for reading its own env-var conventions and passing values explicitly. This keeps the library reusable by any MCP server without env-var collisions.

### Minimal sketch (subject to v0.1.0 release)

```python
from mcp_microsoft_graph_auth import (
    request_device_code,
    poll_for_token,
    refresh_access_token,
    CachedToken,
    PlainFileTokenStore,
)

# Initiate Device Code flow
device_code, challenge = request_device_code(
    client_id="<your-app-id>",
    tenant="organizations",  # or a specific tenant GUID
    scopes=("Files.ReadWrite.All", "Sites.ReadWrite.All", "User.Read", "offline_access"),
)
print(f"Open {challenge.verification_uri} and enter code {challenge.user_code}")

# Poll until the user completes sign-in
token = poll_for_token(
    device_code=device_code,
    client_id="<your-app-id>",
    interval=challenge.interval,
)

# Persist for later
store = PlainFileTokenStore(base_dir="~/.cache/my-mcp-server")
store.set("default", token.to_json().encode())
```

## Compatibility

- Python 3.11+
- Microsoft Identity v2.0 endpoints
- Tested on Linux + macOS (Windows should work; not yet covered by CI)

## License

Dual-licensed under MIT or Apache-2.0 at your option. See [LICENSE-MIT](LICENSE-MIT) and [LICENSE-APACHE](LICENSE-APACHE).

## Status

**Pre-1.0.** The public API is stable enough for use by `mcp-server-sharepoint` and `mcp-server-outlook` — the two consumers driving its design. External consumption is welcome but expect occasional breaking changes until v1.0.

See [`docs/RELEASING.md`](docs/RELEASING.md) for release process and [`CHANGELOG.md`](CHANGELOG.md) for what's shipped.
