<!-- SPDX-License-Identifier: MIT OR Apache-2.0 -->
# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

No entries.

## [v0.1.0] — 2026-05-08

First public release. Five modules extracted / authored, all tests green, public API stable enough for two known consumers (`mcp-server-sharepoint`, `mcp-server-outlook`) to depend on.

### Added — public API

- **`device_code`** — OAuth Device Code primitives against Microsoft Identity v2.0 (`request_device_code`, `poll_for_token`, `refresh_access_token`). Prefix-agnostic: `client_id` and `scopes` are required parameters; `tenant` defaults to `"organizations"`. Errors: `DeviceCodeError`, `AuthorizationDeniedError`, `DeviceCodeExpiredError`, `RefreshTokenInvalidError`. Value type: `DeviceCodeChallenge`.
- **`tokens`** — `CachedToken` dataclass with `to_json()` / `from_json()` / `is_expired()`.
- **`token_store`** — `TokenStore` Protocol + three backends:
  - `KeyringTokenStore(service_name=)` — OS keyring (Keychain / Credential Locker / Secret Service).
  - `PlainFileTokenStore(base_dir=)` — JSON file mode 0600.
  - `EncryptedFileTokenStore(base_dir=, passphrase=)` — Fernet ciphertext + Scrypt KDF.
  - `is_real_keyring_backend()` helper for consumers' auto-pick logic.
- **`service_principal`** — client-credentials grant for unattended automation. `acquire_app_only_token()` primitive + `AppOnlyTokenCache` class for in-process caching keyed by `(client_id, tenant)`. Pinned `SERVICE_PRINCIPAL_SCOPE` constant.
- **`login_session`** — data + registry for MCP-tool-driven Device Code login flows. `LoginSession` dataclass, `LoginSessionRegistry` (thread-safe via `threading.RLock`, with atomic `put_if_absent` for first-write-wins semantics), `public_view()` helper that critically excludes the secret `device_code` from tool output.

### Design decisions

- **Prefix-agnostic.** No environment-variable reading inside the library. Each consumer (`mcp-server-sharepoint` reads `SP_*`, `mcp-server-outlook` reads `OUTLOOK_*`) passes values explicitly.
- **No MCP SDK dependency.** The library is MCP-server-agnostic; only its consumers depend on `mcp`.
- **Login sessions are process-local.** Persisting them across restarts would require serialising an `asyncio.Task`, which is non-trivial; the limitation is documented and consumers warn users in their READMEs.
- **Asyncio orchestration lives in the consumer.** `LoginSessionRegistry` provides data + thread-safe mutations only; consumers wire their own `asyncio.create_task` lifecycle.

### Tests

- 88 unit tests, all green
- Lint clean (ruff), format clean, mypy `--strict` clean
- Three-layer test discipline (unit / integration / harness) per the engineering principles; harness layer pending until a test tenant is provisioned for this library specifically
