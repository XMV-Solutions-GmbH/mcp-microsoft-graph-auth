<!--
SPDX-License-Identifier: MIT OR Apache-2.0
SPDX-FileCopyrightText: 2026 XMV Solutions GmbH
SPDX-FileContributor: David Koller <david.koller@xmv.de>
-->

# PROJECT_SPECIFICS.md — `mcp-microsoft-graph-auth`

Project-specific content for `mcp-microsoft-graph-auth`. Read after `AGENTS.md` per its reading order. Everything in here is specific to this repo; the generic agent rules live in `AGENTS.md` + `ENGINEERING_PRINCIPLES.md` + `PROJECT_MANAGEMENT_PRINCIPLES.md`.

## What this project is

`mcp-microsoft-graph-auth` — a **shared library** of Microsoft Graph authentication helpers used by [`mcp-server-sharepoint`](https://github.com/XMV-Solutions-GmbH/sharepoint-mcp) and [`mcp-server-outlook`](https://github.com/XMV-Solutions-GmbH/outlook-mcp) (and likely future siblings — Teams, OneDrive, …). It is the **shared auth building block the other MCP servers depend on**, factoring out the OAuth machinery so each MCP server adds only what is specific to its API surface (scopes + tool names).

This repo derives from a shared MCP-server template; generic MCP boilerplate is covered by the Canon agent docs. The genuinely project-specific core is the **auth-flow contract** documented below.

It owns:

- **OAuth Device Code flow** against Microsoft Identity v2.0 (`request_device_code`, `poll_for_token`, `refresh_access_token`).
- **Service-principal / client-credentials grant** for unattended automation (CI runners, scheduled jobs).
- **Token cache backends**: OS keyring, plain-file (mode 0600), encrypted-file (Fernet + Scrypt KDF).
- **`CachedToken`** dataclass + JSON helpers.
- **`LoginSession` + `LoginSessionRegistry`** — in-process state for MCP-tool-driven login flows (`*_login_begin` / `*_login_status`).

### Scope discipline

This is a focused library, not a Microsoft-auth swiss army knife. Explicitly **out of scope**:

- Non-Graph OAuth providers (Google, Slack, …).
- MCP server runtime / tool registration — that is the consumer's job.
- Service-specific helpers (mail send, drive item, …) — that is the consumer's job.
- Any env-var reading. The library takes explicit `client_id` / `tenant` / `client_secret` parameters; consumers read their own env-var conventions and pass values in.

## Public API contract (prefix-agnostic)

The library is **prefix-agnostic**: it does **not** read environment variables on its own. Each consumer (an MCP server) is responsible for reading its own env-var conventions (`SP_*` for sharepoint, `OUTLOOK_*` for outlook) and passing values explicitly to the library's primitives.

Why: the library would otherwise need to know about every consumer's prefix, or pick a single "lib prefix" that consumers have to translate to. Both are awkward. Explicit args sidestep the whole problem and keep the library reusable by any MCP server without env-var collisions.

## MCP integration specifics

These are the auth-flow specifics that downstream MCP servers depend on. They are the load-bearing, project-specific content — preserve them.

### How tools are presented (the login-flow tool pair)

Consumers wrap the Device Code flow as a pair of MCP tools, sharing in-process state through this library's `LoginSessionRegistry`:

- `*_login_begin` — starts a Device Code flow; returns `{verification_url, user_code, ...}`.
- `*_login_status` — polls the shared session until sign-in completes.

The `*` prefix is the consumer's (e.g. `sp_login_begin`, `ol_login_begin`); the library is prefix-agnostic about it.

### How code is emitted / returned on sign-in (auth-flow contract)

The Device Code flow returns the `user_code` and `verification_url` to the agent. The MCP tool's description must instruct the agent how to render those two values, because mobile / smartphone agent UIs are strict about both shape and ordering:

- **`user_code` first**, alone in its own one-line code block, with no labels like `Code:` and no whitespace padding. Long-press / tap-and-hold copy then yields just the code.
- **`verification_url` second**, on its own line.

Ordering rationale: the user's optimal workflow is *copy the code → click the link → paste the code into the page that just opened*. With the code first, the clipboard is loaded before the user leaves the chat. URL-first would force chat-↔-browser ping-pong.

Recommended verbatim phrasing for the consuming tool's MCP description:

> When surfacing the result to the user, render `user_code` FIRST in its own code block (no labels, no whitespace) and `verification_url` SECOND as a plain auto-link (not in a code block). The user copies the code first, then clicks the link, and pastes into the page that opens — minimises app-switching on mobile.

### How the markdown link is formed

The `verification_url` is rendered as a **plain Markdown auto-link** (`https://…`), **not** inside a code block — code blocks suppress link rendering, so on mobile the user cannot tap it.

The CLI fallback (`mcp-server-<svc> login`) instead prints `URL:` / `Code:` labels in URL-then-Code order because terminals lack rich rendering — that format is correct for stderr and **wrong** to relay verbatim into chat.

### How the test-harness works

Three-layer test model from `ENGINEERING_PRINCIPLES.md` § 5, auto-marked by directory via `tests/conftest.py` (`pytest_collection_modifyitems` tags each test `unit` / `integration` / `harness` from its path):

- **Unit** (`tests/unit/`) — pure-function tests, all externals mocked, sub-second.
- **Integration** (`tests/integration/`) — boundary-mock tests with `respx`-mocked Microsoft Identity (no real tenant).
- **Harness** (`tests/harness/`) — tests against a **real Microsoft Identity tenant**; skipped when credentials are unavailable. The harness layer is scaffolded (`tests/harness/__init__.py`) but no harness tests are written yet.

Run via `./tests/run_tests.sh` (unit + integration) or `./tests/run_tests.sh harness` (real tenant, needs creds). Markers are declared in `pyproject.toml` (`[tool.pytest.ini_options].markers`).

### MCP-install test

Not applicable to this repo: it is a **library**, not an installable MCP server, so it exposes no MCP tool suite of its own. The sub-agent-knows-only-the-tool-suite install test lives in the **consumer** repos (`mcp-server-sharepoint`, `mcp-server-outlook`), exercising the tools this library powers.

## Project-specific docs

| Doc | Purpose |
|---|---|
| [`README.md`](README.md) | Why this exists, what's in the box, public-API sketch, UX guidance for relaying the verification URL + code |
| [`docs/RELEASING.md`](docs/RELEASING.md) | Release process — PyPI Trusted Publisher (OIDC), SemVer, hotfix flow, consumer-coordination |
| [`CONTRIBUTING.md`](CONTRIBUTING.md) | Scope discipline, code conventions, three-layer test discipline, PR flow |
| [`SECURITY.md`](SECURITY.md) | How to report security issues |
| [`CHANGELOG.md`](CHANGELOG.md) | Keep-a-changelog history |

## Tracker

**GitHub Issues + GitHub Projects** at <https://github.com/XMV-Solutions-GmbH/mcp-microsoft-graph-auth/issues>. See `ENGINEERING_PRINCIPLES.md` § 2.

Same labelling conventions as `sharepoint-mcp`:

- `type:feat` / `type:fix` / `type:chore` / `type:docs` / `type:test`
- `area:device-code` / `area:token-store` / `area:service-principal` / `area:login-session` / `area:ci` / `area:packaging` / `area:docs`
- `priority:p0` / `p1` / `p2`
- `agent:claude` when an AI agent is the executor.

Issue body convention: `## Context`, `## Acceptance criteria` (checkbox list), `## Out of scope`, `## Links`. Milestones map to releases.

## Tech stack

- **Python 3.11+**, hatchling build backend.
- **`httpx`** for Microsoft Identity HTTP calls (sync; consumer wraps in `asyncio.to_thread` if needed).
- **`keyring`** (optional dep on Linux for Secret Service) + **`cryptography`** for the encrypted-file backend.
- **No `mcp` SDK dependency.** This library is MCP-server-agnostic; only the consumers depend on `mcp`.
- **Tests**: pytest + `pytest-asyncio` + `respx` for HTTP boundary mocks; `pytest-cov` for coverage. Three layers (unit / integration / harness).
- **Lint/format**: `ruff` (line-length 100, target py311), `mypy --strict`.
- **Packaging/distribution**: published to PyPI as `mcp-microsoft-graph-auth` via PyPI Trusted Publisher (OIDC, `release.yml` on `v*` tag).

## Project-specific overrides of the engineering baseline

- **Licensing (overrides `ENGINEERING_PRINCIPLES.md` § 11) — two ownership classes.** This repo's own deliverable code and docs are **OSS, dual-licensed `MIT OR Apache-2.0`** at the user's option — see [`LICENSE-MIT`](LICENSE-MIT) and [`LICENSE-APACHE`](LICENSE-APACHE). There is no single `LICENSE` file. Every *repo-owned* source file (code, `PROJECT_SPECIFICS.md`, the tool-specific pointer files) uses `SPDX-License-Identifier: MIT OR Apache-2.0`, copyright `XMV Solutions GmbH`, human author as `SPDX-FileContributor`. **Exception — the Canon docs.** `AGENTS.md`, `ENGINEERING_PRINCIPLES.md` and `PROJECT_MANAGEMENT_PRINCIPLES.md` are XMV's cross-project IP distributed into this repo unchanged; they keep their own `SPDX-License-Identifier: LicenseRef-XMV-Proprietary` header and are **not** relicensed by being copied here (SPDX is per-file; a mixed-licence repo is normal). Both `LICENSE-MIT` and `LICENSE-APACHE` are exempt from headers (they *are* the licences). The § 11 body text referring to a single `LICENSE` file does not apply to this repo's OSS files.
- **PR workflow already triggered (per § 13).** Public OSS library; `main` is deployable trunk. Feature branches + PRs, branch protection, CI green required for merge. One reviewer approval + green CI = mergeable. Squash-merge by default; keep linear history.
- **Two consumers steer the design.** Public-API decisions are weighed against `mcp-server-sharepoint` and `mcp-server-outlook` first; external consumption is welcome but does not dictate the API. A breaking change here means follow-up PRs in both consumer repos *before* the major lands — the release is not done until both consumers' CI is still green.

## Environments + URLs

- **Repo**: <https://github.com/XMV-Solutions-GmbH/mcp-microsoft-graph-auth>
- **PyPI**: <https://pypi.org/project/mcp-microsoft-graph-auth/> (Trusted Publisher; `pypi` deployment environment in repo settings)
- **Identity endpoints**: Microsoft Identity platform v2.0 (Device Code + token).
- **Harness CI secret**: `MCP_GRAPH_AUTH_HARNESS_TOKEN_JSON`. Microsoft refresh tokens rotate every ~60–90 days, so the same monthly token-renewal chore as the consumer projects applies. A renewal script (`scripts/renew-harness-token.sh`, ported from the sharepoint-mcp pattern) is TBD until harness tests land.
- **Contact**: <oss@xmv.de> for non-public matters; GitHub Discussions for design questions.

## Glossary

- **Device Code flow** — OAuth 2.0 grant where the user authorises on a second device by entering a short `user_code` at a `verification_url`. The primary interactive auth path for this library.
- **Service principal / client-credentials grant** — non-interactive grant for unattended automation (CI, scheduled jobs).
- **`CachedToken`** — dataclass holding an access/refresh token pair plus expiry, with JSON serialisation for the token stores.
- **`LoginSession` / `LoginSessionRegistry`** — in-process state shared between a consumer's `*_login_begin` and `*_login_status` MCP tools across the polling lifetime of a Device Code flow.
- **Token store backends** — OS keyring, plain-file (mode 0600, `~/.cache/<app>/<profile>/token.json`), and encrypted-file (Fernet + Scrypt KDF).
- **Prefix-agnostic** — the library never reads env vars; consumers pass `client_id` / `tenant` / `client_secret` explicitly, using their own `SP_*` / `OUTLOOK_*` conventions.
- **Consumer** — an MCP server that depends on this library (`mcp-server-sharepoint`, `mcp-server-outlook`, future siblings).
