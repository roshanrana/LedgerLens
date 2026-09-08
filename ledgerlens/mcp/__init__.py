"""MCP surface for LedgerLens: the human review gate exposed to any MCP client.

``ledgerlens.mcp.server`` is imported lazily so ``python -m ledgerlens.mcp.server`` runs the
module exactly once (an eager import here would make runpy warn that the module is already
in ``sys.modules``).
"""

from __future__ import annotations

from typing import Any

_EXPORTS = ("DEFAULT_DB_PATH", "ENV_DB_PATH", "SERVER_NAME", "TOOL_NAMES", "build_server", "main")

__all__ = list(_EXPORTS)


def __getattr__(name: str) -> Any:
    if name in _EXPORTS:
        from ledgerlens.mcp import server

        return getattr(server, name)
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
