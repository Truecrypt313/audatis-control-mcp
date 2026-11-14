"""Strictly additive registration; no aliases or changes to the old 47 tools."""
from management_tools import MANAGEMENT_TOOLS
from management_catalog import get_catalog
from v2_register import _report_errors


def register_management_tools(mcp) -> None:
    tools = tuple(MANAGEMENT_TOOLS)
    if hasattr(mcp, "summary"):
        existing = {name for module in mcp.summary()["modules"].values() for name in module["catalog_tools"]}
        if existing.intersection(tool.__name__ for tool in tools) or any(
                tool.__name__ == "module_capabilities" for tool in tools):
            catalog = get_catalog()
            catalog.status = "invalid"
            catalog.operations.clear()
            catalog.spec.clear()
            return
    for tool in tools:
        mcp.tool()(_report_errors(tool))
