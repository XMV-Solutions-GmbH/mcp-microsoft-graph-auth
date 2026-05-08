<!-- SPDX-License-Identifier: MIT OR Apache-2.0 -->

# Releasing mcp-microsoft-graph-auth

Steps to cut a new version. Follows [Semantic Versioning](https://semver.org/).

---

## Prerequisites (one-time)

### PyPI Trusted Publisher

This project uses [PyPI Trusted Publishers](https://docs.pypi.org/trusted-publishers/) for OIDC-based publishing — no long-lived API tokens stored anywhere. Setup steps:

1. **Reserve the project name on PyPI** (one-off):
   - Log in at <https://pypi.org/>.
   - Go to "Your projects" → "Add a pending publisher".
   - PyPI Project Name: `mcp-microsoft-graph-auth`
   - Owner: `XMV-Solutions-GmbH`
   - Repository name: `mcp-microsoft-graph-auth`
   - Workflow name: `release.yml`
   - Environment name: `pypi`
2. **Add a `pypi` deployment environment** in this repo (Settings → Environments → New environment "pypi"). Optional: require manual approval for production releases.
3. After the first successful publish, the pending-publisher record converts to a regular Trusted Publisher; subsequent releases just work.

### Alternative: API token

If Trusted Publisher isn't available (e.g., for private mirrors), generate a PyPI API token at <https://pypi.org/manage/account/token/> and store it as repo secret `PYPI_API_TOKEN`. Then change `release.yml`'s publish step to:

```yaml
- name: Publish to PyPI (API token)
  env:
    UV_PUBLISH_TOKEN: ${{ secrets.PYPI_API_TOKEN }}
  run: uv publish
```

Trusted Publisher is preferred — fewer secrets to rotate.

---

## Cutting a release

For a normal release (version bumps follow SemVer; v0.x increments freely while pre-1.0):

```bash
# 1. Update CHANGELOG.md — move [Unreleased] entries under a new versioned section
$EDITOR CHANGELOG.md

# 2. Bump version in pyproject.toml
$EDITOR pyproject.toml   # change version = "x.y.z"

# 3. Commit
git add CHANGELOG.md pyproject.toml
git commit -m "chore(release): vX.Y.Z"
git push origin main

# 4. Wait for CI green on main

# 5. Tag + push
git tag -a vX.Y.Z -m "Release vX.Y.Z"
git push origin vX.Y.Z
```

The `release.yml` workflow triggers on `v*` tag push:

1. Re-runs unit + integration tests as a gate.
2. Builds wheel + sdist via `uv build`.
3. Publishes to PyPI via OIDC.
4. Creates a GitHub Release with auto-generated notes.

Verify the published artifact:

```bash
pip install --upgrade mcp-microsoft-graph-auth==X.Y.Z
python -c "import mcp_microsoft_graph_auth; print(mcp_microsoft_graph_auth.__version__)"
```

---

## Hotfix flow

For a bugfix on top of a release that's now diverged from `main`:

```bash
git checkout vX.Y.0
git checkout -b hotfix/X.Y.1
# ... fix ...
git tag -a vX.Y.1 -m "Hotfix vX.Y.1"
git push origin vX.Y.1
```

Then port the fix forward to `main` via PR.

---

## Coordinating releases with consumers

This library has two known consumers: `mcp-server-sharepoint` and `mcp-server-outlook`. Breaking changes here mean follow-up PRs in those repos.

- **Patch / minor** (additive): consumers usually just bump their `pyproject.toml` dependency on the next routine release.
- **Major** (breaking): open follow-up PRs in both consumer repos *before* the major lands here. They can pin to the previous major until they're updated. The release isn't done until both consumers' CI is still green.

---

## When to bump major / minor / patch

While pre-1.0:

- **Patch** (`v0.x.Y → v0.x.(Y+1)`): bug fixes, doc updates, internal refactors. No public-API changes.
- **Minor** (`v0.X.* → v0.(X+1).0`): new public-API surface that doesn't break existing consumers.
- **Major** (`v0.* → v1.0.0`): the first stable release. Document SemVer commitments in CHANGELOG. After v1.0, breaking changes require a major bump and a deprecation cycle.

For v0.1 specifically: the entire v0.1 line is "alpha — APIs may change between minor versions". Both internal consumers tolerate this; external consumers should pin tightly.
