<!--
SPDX-License-Identifier: MIT OR Apache-2.0
SPDX-FileCopyrightText: 2026 XMV Solutions GmbH
SPDX-FileContributor: David Koller <david.koller@xmv.de>
-->

# Project conventions — mcp-microsoft-graph-auth

**Read [ENGINEERING_PRINCIPLES.md](ENGINEERING_PRINCIPLES.md) first.** It is the project-agnostic baseline (language rule, status workflow, AI-as-developer test-harness requirement, source-control rules, documentation baseline). This file only adds notes specific to this repository.

---

## What this repo is

A **shared library** of Microsoft Graph auth helpers used by [`mcp-server-sharepoint`](https://github.com/XMV-Solutions-GmbH/sharepoint-mcp) and [`mcp-server-outlook`](https://github.com/XMV-Solutions-GmbH/outlook-mcp). Owns:

- OAuth Device Code flow (request → poll → refresh).
- Token cache backends: OS keyring, plain-file mode 0600, encrypted-file (Fernet + Scrypt).
- `CachedToken` dataclass + JSON helpers.
- Service-principal / client-credentials grant for unattended automation.
- `LoginSessionRegistry` — in-process state for MCP-tool-driven login flows (`*_login_begin` / `*_login_status`).

**Scope discipline.** This is a focused library, not a Microsoft-auth swiss army knife. Things explicitly out of scope:

- Non-Graph OAuth providers (Google, Slack, …).
- MCP server runtime / tool registration — that's the consumer's job.
- Service-specific helpers (mail send, drive item, …) — that's the consumer's job.
- Any env-var reading. The library takes explicit `client_id` / `tenant` / `client_secret` parameters; consumers read their own env-var conventions and pass values in.

## Public API contract (prefix-agnostic)

The library does **not** read environment variables. Each consumer (an MCP server) is responsible for reading its own env-var conventions (`SP_*` for sharepoint, `OUTLOOK_*` for outlook) and passing values explicitly to the library's primitives.

Why: the library would otherwise need to know about every consumer's prefix, or pick a single "lib prefix" that consumers have to translate to. Both are awkward. Explicit args sidestep the whole problem.

## Project-specific tracking

**Authoritative tracker: GitHub Issues + GitHub Projects** at <https://github.com/XMV-Solutions-GmbH/mcp-microsoft-graph-auth/issues>.

Same labelling conventions as sharepoint-mcp:

- `type:feat` / `type:fix` / `type:chore` / `type:docs` / `type:test`
- `area:device-code` / `area:token-store` / `area:service-principal` / `area:login-session` / `area:ci` / `area:packaging` / `area:docs`
- `priority:p0` / `p1` / `p2`
- `agent:claude` when an AI agent is the executor.

Issue body convention: **Context** · **Acceptance criteria** (checkbox list) · **Out of scope** · **Links**.

## Tech stack

- **Python 3.11+**, hatchling build backend.
- **`httpx`** for Microsoft Identity HTTP calls (sync; consumer wraps in `asyncio.to_thread` if needed).
- **`keyring`** (optional dep on Linux for Secret Service) + **`cryptography`** for the encrypted-file backend.
- **No `mcp` SDK dependency.** This library is MCP-server-agnostic; only the consumers depend on `mcp`.
- **Tests**: pytest + `respx` for HTTP boundary mocks. Three layers (unit / integration / harness).
- **Lint/format**: ruff, mypy strict.

## License & attribution

Per [ENGINEERING_PRINCIPLES.md](ENGINEERING_PRINCIPLES.md) §§ 11-12:

- **License**: dual-licensed **MIT OR Apache-2.0** — see [LICENSE-MIT](LICENSE-MIT), [LICENSE-APACHE](LICENSE-APACHE).
- **Copyright holder**: XMV Solutions GmbH.
- **SPDX license identifier** for file headers: `MIT OR Apache-2.0`.

### Header to add to every new source file

Python / Shell / YAML / TOML:

```text
# SPDX-License-Identifier: MIT OR Apache-2.0
# SPDX-FileCopyrightText: <year> XMV Solutions GmbH
# SPDX-FileContributor: <git user.name> <<git user.email>>
```

HTML / Markdown:

```html
<!--
SPDX-License-Identifier: MIT OR Apache-2.0
SPDX-FileCopyrightText: <year> XMV Solutions GmbH
SPDX-FileContributor: <name> <<email>>
-->
```

### What NOT to do

- Never add `Co-Authored-By: Claude …` (or any AI tool) to commit messages.
- Never put AI tool names or versions into source comments.
- Never list an AI as a `SPDX-FileContributor`.

## Project-specific overrides of the engineering baseline

- **PR workflow already triggered (per § 13).** This is a public OSS library; `main` is deployable trunk. Feature branches + PRs, branch protection, CI green required for merge.
- **Two consumers steer the design.** Public-API decisions are weighed against `mcp-server-sharepoint` and `mcp-server-outlook` first; external consumption is welcome but doesn't dictate the API.
- **Harness token renewal.** Same monthly chore as in the consumer projects — Microsoft refresh tokens rotate every ~60-90 days. The harness CI secret here is `MCP_GRAPH_AUTH_HARNESS_TOKEN_JSON`. Renewal script lives in this repo at `scripts/renew-harness-token.sh` (TBD — port from the sharepoint-mcp pattern when harness tests land).
- **No proprietary headers.** This repo is OSS — every header uses `SPDX-License-Identifier: MIT OR Apache-2.0`.
