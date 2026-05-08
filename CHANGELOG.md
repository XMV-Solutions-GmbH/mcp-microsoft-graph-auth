<!-- SPDX-License-Identifier: MIT OR Apache-2.0 -->
# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Added

- Repo bootstrap: pyproject (hatchling, dual MIT OR Apache-2.0), CI (lint / test / harness), release workflow (PyPI Trusted Publisher OIDC), engineering principles + security policy + markdown lint config.
- Initial planned modules — `device_code`, `tokens`, `service_principal`, `token_store`, `login_session` — extracted from `mcp-server-sharepoint`'s `auth/` package. See [`docs/RELEASING.md`](docs/RELEASING.md) and [README](README.md) for the public-API sketch.

## [v0.1.0] — TBD

First public release. Will land once the auth modules are extracted from `mcp-server-sharepoint` and `mcp-server-sharepoint` switches to depend on this library.
