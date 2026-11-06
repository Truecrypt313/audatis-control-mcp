"""Register additive V2 tools without replacing any existing tool."""
from __future__ import annotations

from functools import wraps
from inspect import signature

from v2_tools import (
    v2_capabilities, v2_list_records, v2_get_record, v2_lookup,
    v2_create_record, v2_update_record, v2_list_incident_links,
    v2_link_incident, v2_audit_log,
)
from v2_bulk import v2_bulk_create_records, v2_bulk_update_records
from v2_analysis import (v2_inventory_snapshot, v2_asset_graph,
                         v2_documentation_gaps, v2_duplicate_tasks)

V2_TOOLS = (
    v2_capabilities,
    v2_list_records,
    v2_get_record,
    v2_lookup,
    v2_create_record,
    v2_update_record,
    v2_list_incident_links,
    v2_link_incident,
    v2_audit_log,
    v2_bulk_create_records,
    v2_bulk_update_records,
    v2_inventory_snapshot,
    v2_asset_graph,
    v2_documentation_gaps,
    v2_duplicate_tasks,
)


def _report_errors(tool):
    """Keep MCP names/signatures; return sanitized, actionable expected errors.

    Unexpected exceptions intentionally propagate rather than masking programming bugs.
    A failed HTTP write can have an uncertain remote outcome; callers must read back
    the resource before deciding whether to retry.
    """
    @wraps(tool)
    def run(*args, **kwargs):
        try:
            return tool(*args, **kwargs)
        except ValueError as exc:
            return {
                "ok": False,
                "tool": tool.__name__,
                "error_type": "validation_error",
                "error": str(exc),
            }
        except RuntimeError as exc:
            return {
                "ok": False,
                "tool": tool.__name__,
                "error_type": "operation_error",
                "error": str(exc),
                "warning": "Bei möglichen Schreibfehlern Remote-Zustand vor erneutem Aufruf prüfen.",
            }

    # Some MCP implementations inspect the public signature to build JSON schemas.
    run.__signature__ = signature(tool)
    return run


def register_v2_tools(mcp) -> None:
    for tool in V2_TOOLS:
        mcp.tool()(_report_errors(tool))
