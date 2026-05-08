# SPDX-License-Identifier: MIT OR Apache-2.0
# SPDX-FileCopyrightText: 2026 XMV Solutions GmbH
# SPDX-FileContributor: David Koller <david.koller@xmv.de>
"""Shared Microsoft Graph auth helpers for MCP servers.

Public API will be populated as modules land. Currently a stub —
the source-of-truth is being extracted from `mcp-server-sharepoint`'s
`sharepoint_mcp.auth` package, see issue #2 (and the `extract auth
modules` task in this repo's project board).

Compatibility: Python 3.11+. The library is prefix-agnostic — it
does not read environment variables on its own. Each consumer reads
its own env-var conventions and passes values explicitly to the
primitives.
"""

from __future__ import annotations

__version__ = "0.0.1.dev0"

__all__ = ["__version__"]
