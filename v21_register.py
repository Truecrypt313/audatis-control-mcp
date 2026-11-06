"""Non-invasive registration: 5 additive tools; original 31 remain unchanged."""
from __future__ import annotations

from functools import wraps
from inspect import signature

from v21_relationships import (
    v21_relationship_capabilities,
    v21_relationship_graph,
    v21_related_records,
    v21_relationship_audit,
)
from v21_hierarchy import v21_bulk_set_parent

V21_TOOLS = (
    v21_relationship_capabilities,
    v21_relationship_graph,
    v21_related_records,
    v21_relationship_audit,
    v21_bulk_set_parent,
)


def _safe(fn):
    @wraps(fn)
    def wrapped(*args, **kwargs):
        try:
            return fn(*args, **kwargs)
        except ValueError as exc:
            return {"ok": False, "tool": fn.__name__, "error_type": "validation_error",
                    "error": str(exc)}
        except RuntimeError as exc:
            return {"ok": False, "tool": fn.__name__, "error_type": "operation_error",
                    "error": str(exc), "warning": "Remote-Zustand vor Wiederholung prüfen."}
    wrapped.__signature__ = signature(fn)
    return wrapped


def register_v21_tools(mcp) -> None:
    """Call after register_v2_tools(mcp), no replacement/renaming of old tools."""
    for fn in V21_TOOLS:
        mcp.tool()(_safe(fn))
