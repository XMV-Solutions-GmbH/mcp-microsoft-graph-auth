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

## UX guidance for relaying the verification URL + user code

When an MCP server wraps the Device Code flow as a tool (e.g. `sp_login_begin` returns `{verification_url, user_code, ...}`), the tool's description should tell the agent **how** to render those two values to the user. Mobile / smartphone agent UIs are strict about both shape and ordering:

- **`user_code` first**, alone in its own one-line code block, with no labels like `Code:` and no whitespace padding. Long-press / tap-and-hold copy then yields just the code.
- **`verification_url` second**, on its own line as a plain Markdown auto-link, **not** inside a code block (code blocks suppress link rendering, so on mobile the user can't tap it).

Why this ordering: the user's optimal workflow is *copy the code → click the link → paste the code into the page that just opened*. With the code first, the clipboard is loaded before the user leaves the chat. URL-first would force a chat-↔-browser ping-pong.

Recommended verbatim phrasing for the tool's MCP description:

> When surfacing the result to the user, render `user_code` FIRST in its own code block (no labels, no whitespace) and `verification_url` SECOND as a plain auto-link (not in a code block). The user copies the code first, then clicks the link, and pastes into the page that opens — minimises app-switching on mobile.

The CLI fallback (`mcp-server-<svc> login`) prints `URL:` / `Code:` labels in URL-then-Code order because terminals don't have rich rendering — that format is correct for stderr and wrong to relay verbatim into chat.

## Compatibility

- Python 3.11+
- Microsoft Identity v2.0 endpoints
- Tested on Linux + macOS (Windows should work; not yet covered by CI)

## License

Dual-licensed under MIT or Apache-2.0 at your option. See [LICENSE-MIT](LICENSE-MIT) and [LICENSE-APACHE](LICENSE-APACHE).

## Status

**Pre-1.0.** The public API is stable enough for use by `mcp-server-sharepoint` and `mcp-server-outlook` — the two consumers driving its design. External consumption is welcome but expect occasional breaking changes until v1.0.

See [`docs/RELEASING.md`](docs/RELEASING.md) for release process and [`CHANGELOG.md`](CHANGELOG.md) for what's shipped.
