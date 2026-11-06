"""Add 11 descriptive, UNVERSIONED MCP tool names. Existing 36 names are unchanged."""
from __future__ import annotations

from v2_register import _report_errors
from personnel_tools import (
    personnel_capabilities,
    list_organisations,
    get_organisation,
    list_personnel,
    get_personnel,
    create_personnel,
    update_personnel,
    assign_personnel_organisations,
    list_personnel_tags,
    get_user,
    get_personnel_assignments,
)

PERSONNEL_TOOLS = (
    personnel_capabilities,
    list_organisations,
    get_organisation,
    list_personnel,
    get_personnel,
    create_personnel,
    update_personnel,
    assign_personnel_organisations,
    list_personnel_tags,
    get_user,
    get_personnel_assignments,
)


def register_personnel_tools(mcp) -> None:
    """Register alongside existing tools, never replace their names or implementations."""
    for fn in PERSONNEL_TOOLS:
        mcp.tool()(_report_errors(fn))
