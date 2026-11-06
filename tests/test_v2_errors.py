"""Offline regression tests for MCP-facing V2 errors; never touch the API."""
import inspect
import json

from v2_register import V2_TOOLS, register_v2_tools


class CapturingMCP:
    def __init__(self):
        self.registry = {}

    def tool(self):
        def install(fn):
            if fn.__name__ in self.registry:
                raise AssertionError(f"Duplicate MCP tool: {fn.__name__}")
            self.registry[fn.__name__] = fn
            return fn
        return install


def test_all_15_tool_names_and_signatures_stay_identical():
    mcp = CapturingMCP()
    register_v2_tools(mcp)
    assert len(mcp.registry) == len(V2_TOOLS) == 15
    for original in V2_TOOLS:
        wrapped = mcp.registry[original.__name__]
        assert inspect.signature(wrapped) == inspect.signature(original)
        assert wrapped.__name__ == original.__name__
        assert wrapped.__doc__ == original.__doc__


def test_invalid_bulk_dry_run_returns_actionable_error(monkeypatch):
    # No network access even if a regression accidentally attempts it.
    import v2_bulk
    monkeypatch.setattr(v2_bulk.V2API, "from_env", staticmethod(
        lambda: (_ for _ in ()).throw(AssertionError("Unexpected network"))
    ))
    mcp = CapturingMCP()
    register_v2_tools(mcp)
    f = mcp.registry["v2_bulk_create_records"]
    out = f(resource="tasks", items_json=json.dumps([
        {"subject": "MCP-Test", "unknown_field": "invalid"}
    ]), execute=False, check_existing=True)
    assert out["ok"] is False
    assert out["error_type"] == "validation_error"
    assert out["tool"] == "v2_bulk_create_records"
    assert "unknown_field" in out["error"]


def test_valid_bulk_preview_still_works_without_api(monkeypatch):
    import v2_bulk
    monkeypatch.setattr(v2_bulk.V2API, "from_env", staticmethod(
        lambda: (_ for _ in ()).throw(AssertionError("Unexpected network"))
    ))
    mcp = CapturingMCP()
    register_v2_tools(mcp)
    out = mcp.registry["v2_bulk_create_records"](
        resource="tasks", items_json='[{"subject":"Safe test"}]', execute=False
    )
    assert out["execute"] is False
    assert out["count"] == 1


def test_internal_runtime_error_is_reported_as_unconfirmed_operation(monkeypatch):
    import v2_tools
    monkeypatch.setattr(v2_tools.V2API, "from_env", staticmethod(
        lambda: (_ for _ in ()).throw(RuntimeError("Test: service temporarily unavailable"))
    ))
    mcp = CapturingMCP()
    register_v2_tools(mcp)
    out = mcp.registry["v2_list_records"](resource="assets")
    assert out["ok"] is False
    assert out["error_type"] == "operation_error"
    assert "service temporarily unavailable" in out["error"]
    assert "vor erneutem Aufruf" in out["warning"]


def test_programming_errors_propagate_instead_of_being_masked(monkeypatch):
    import pytest
    import v2_tools
    monkeypatch.setattr(v2_tools.V2API, "from_env", staticmethod(
        lambda: (_ for _ in ()).throw(TypeError("Unexpected bug"))
    ))
    mcp = CapturingMCP()
    register_v2_tools(mcp)
    with pytest.raises(TypeError, match="Unexpected bug"):
        mcp.registry["v2_list_records"](resource="assets")
