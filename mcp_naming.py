"""Optional public MCP name normalization without touching existing tool logic.

By default legacy tool names are preserved. Enable modern names for the MCP
server process with AUDATIS_MCP_TOOL_NAMES=modern. A *single* public name is
registered for each function, never both aliases at once.
"""
from __future__ import annotations

import os
from functools import wraps
from inspect import signature
from typing import Callable

# Explicit mapping, deliberately NOT a generic arbitrary prefix stripper.
# Changing the public names does not change Python imports or persisted data.
TOOL_NAME_MAP: dict[str, str] = {
    "v2_capabilities": "manager_capabilities",
    "v2_list_records": "list_records",
    "v2_get_record": "get_record",
    "v2_lookup": "lookup_values",
    "v2_create_record": "create_record",
    "v2_update_record": "update_record",
    "v2_list_incident_links": "list_incident_links",
    "v2_link_incident": "link_incident",
    "v2_audit_log": "list_audit_log",
    "v2_bulk_create_records": "bulk_create_records",
    "v2_bulk_update_records": "bulk_update_records",
    "v2_inventory_snapshot": "inventory_snapshot",
    "v2_asset_graph": "asset_graph",
    "v2_documentation_gaps": "documentation_gaps",
    "v2_duplicate_tasks": "find_duplicate_tasks",
    "v21_relationship_capabilities": "relationship_capabilities",
    "v21_relationship_graph": "relationship_graph",
    "v21_related_records": "related_records",
    "v21_relationship_audit": "relationship_audit",
    "v21_bulk_set_parent": "bulk_set_parent",
}

NAMING_ENV = "AUDATIS_MCP_TOOL_NAMES"


def naming_mode() -> str:
    """Validate explicit naming policy. No implicit fallback on typos."""
    value = os.environ.get(NAMING_ENV, "legacy").strip().lower()
    if value not in ("legacy", "modern"):
        raise ValueError(f"{NAMING_ENV} muss 'legacy' oder 'modern' sein")
    return value


def _public_wrapper(function: Callable, public_name: str) -> Callable:
    @wraps(function)
    def named_tool(*args, **kwargs):
        result = function(*args, **kwargs)
        # Normalized error response should name the tool actually called.
        if (isinstance(result, dict)
                and result.get("ok") is False
                and result.get("tool") == function.__name__):
            return {**result, "tool": public_name}
        return result

    named_tool.__name__ = public_name
    named_tool.__qualname__ = public_name
    # MCP schemas are generated from the original, typed Python signature.
    named_tool.__signature__ = signature(function)
    return named_tool


class _ModernNamingProxy:
    """Intercept only mcp.tool()(function), keeping the original API unchanged."""

    def __init__(self, mcp):
        self._mcp = mcp

    def tool(self, *args, **kwargs):
        original_registrar = self._mcp.tool(*args, **kwargs)

        def register(function):
            if function.__name__ not in TOOL_NAME_MAP:
                raise ValueError("Kein expliziter MCP-Namenseintrag für: " + function.__name__)
            public_name = TOOL_NAME_MAP[function.__name__]
            return original_registrar(_public_wrapper(function, public_name))

        return register


def named_mcp(mcp):
    """Return original MCP object in legacy mode or registration proxy in modern mode."""
    if naming_mode() == "legacy":
        return mcp
    return _ModernNamingProxy(mcp)
