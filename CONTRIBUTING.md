<!-- SPDX-License-Identifier: MIT OR Apache-2.0 -->
# Contributing to mcp-microsoft-graph-auth

Thanks for your interest. This is a small, focused library — it intentionally does not try to be everything Microsoft auth could ever be. Contributions that fit the scope are welcome; contributions that broaden the scope (e.g. arbitrary OAuth providers, non-Graph APIs) are unlikely to land.

## Getting started

```bash
git clone https://github.com/XMV-Solutions-GmbH/mcp-microsoft-graph-auth.git
cd mcp-microsoft-graph-auth
uv sync --extra dev

./tests/run_tests.sh         # unit + integration
./tests/run_tests.sh harness # against a real Microsoft Identity tenant (needs creds)
```

## Code conventions

- Python 3.11+, type-checked with `mypy --strict`.
- Formatted with `ruff format`, linted with `ruff check`.
- British English in code, comments, and documentation.
- Every source file starts with an SPDX header — `MIT OR Apache-2.0`, `XMV Solutions GmbH` copyright, your name as `SPDX-FileContributor`. See [ENGINEERING_PRINCIPLES.md § 12](ENGINEERING_PRINCIPLES.md).
- **Do not** add `Co-Authored-By: <AI tool>` lines to commits, code comments, or SPDX headers. AI tooling is not a contributor under German *Urheberrecht*.

## Test discipline

The library uses the three-layer model from [`ENGINEERING_PRINCIPLES.md § 5`](ENGINEERING_PRINCIPLES.md):

- **Unit** — pure-function tests, all externals mocked, sub-second.
- **Integration** — boundary-mock tests (e.g. `respx`-mocked Microsoft Identity).
- **Harness** — tests against a real Microsoft Identity tenant. Skipped when credentials aren't available.

Every behaviour change must include unit tests; integration tests when the change touches HTTP shape; harness tests when it changes the wire contract with Microsoft.

## Pull-request flow

1. Branch off `main`: `feat/<short-description>`, `fix/<…>`, `docs/<…>`, `chore/<…>`.
2. Open a PR against `main`. CI must be green.
3. One reviewer approval + green CI = mergeable.
4. Squash-merge by default; preserve a clean linear history.

Conventional Commits for the PR title (`feat(auth):`, `fix(token-store):`, `docs:`, etc.).

## Reporting issues

- **Bugs**: include reproduction steps, expected vs actual, environment, relevant logs.
- **Feature requests**: state the problem first, then the proposed solution. Be specific about how it interacts with the two consumer projects (`mcp-server-sharepoint`, `mcp-server-outlook`).
- **Security issues**: see [`SECURITY.md`](SECURITY.md). Do not file public issues for security problems.

## Questions?

- Open a GitHub Discussion for design questions.
- Open a GitHub Issue for bug reports / feature requests.
- Email <oss@xmv.de> for anything that shouldn't be public.
