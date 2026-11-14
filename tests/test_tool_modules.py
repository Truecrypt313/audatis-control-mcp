"""Offline profile registration and non-bypass tests, in both naming modes."""
from __future__ import annotations

import hashlib
import importlib
import inspect
import json
import sys
import types
from pathlib import Path

import pytest

from mcp_naming import TOOL_NAME_MAP
from tool_modules import (
    DEPENDENCIES, MODULES, ModuleRegistry, canonical_name, lookup_module,
    parse_modules, tool_module,
)
from v2_core import LOOKUPS
from management_catalog import OPERATIONS


@pytest.fixture
def start_server(monkeypatch):
    class OfflineMCP:
        def __init__(self, name):
            self.tools = {}
        def tool(self):
            def register(fn):
                assert fn.__name__ not in self.tools
                self.tools[fn.__name__] = fn
                return fn
            return register
        def run(self, **kwargs):
            pytest.fail("No stdio transport in tests")

    pkg = types.ModuleType("mcp")
    pkg.__path__ = []
    sdk = types.ModuleType("mcp.server")
    sdk.MCPServer = OfflineMCP
    monkeypatch.setitem(sys.modules, "mcp", pkg)
    monkeypatch.setitem(sys.modules, "mcp.server", sdk)

    def start(profile="all", mode="modern"):
        if profile is None:
            monkeypatch.delenv("AUDATIS_MCP_MODULES", raising=False)
        else:
            monkeypatch.setenv("AUDATIS_MCP_MODULES", profile)
        monkeypatch.setenv("AUDATIS_MCP_TOOL_NAMES", mode)
        monkeypatch.delitem(sys.modules, "server", raising=False)
        return importlib.import_module("server")
    yield start
    monkeypatch.delitem(sys.modules, "server", raising=False)


@pytest.mark.parametrize("value,expected", [
    (None, ("all",)), ("all", ("all",)), (" ALL ", ("all",)),
    ("core,incidents,risks", ("core", "incidents", "risks")),
    (" CORE ,risks,core ", ("core", "risks")),
])
def test_parse_valid_profiles(value, expected):
    assert parse_modules(value) == expected


@pytest.mark.parametrize("value", ["", " ", ",", "core,", ",core", "core,,risks",
                                   "all,incidents", "core,unknown", "core;risks", "a" * 257])
def test_invalid_configuration_fails_closed(value, start_server):
    with pytest.raises(ValueError, match="AUDATIS_MCP_MODULES"):
        start_server(value)


@pytest.mark.parametrize("mode", ["modern", "legacy"])
@pytest.mark.parametrize("profile", [None, "all", ",".join(MODULES)])
def test_all_226_original_tools_unchanged_plus_one_local_overview(profile, mode, start_server):
    server = start_server(profile, mode)
    baseline = json.loads(Path(__file__).with_name("fixtures").joinpath("tools_226.json").read_text())[mode]
    registered = server.mcp.tools
    if not OPERATIONS:
        original = json.loads(Path(__file__).with_name("fixtures").joinpath("original_tools.json").read_text())[mode]
        baseline = {name: entry for name, entry in baseline.items() if name in original}
    assert len(registered) == len(baseline) + 1
    assert set(registered) == set(baseline) | {"module_capabilities"}
    for name, before in baseline.items():
        assert str(inspect.signature(registered[name])) == before["signature"]
        assert hashlib.sha256((registered[name].__doc__ or "").encode()).hexdigest() == before["description_sha256"]
    overview = registered["module_capabilities"]()
    assert overview["available_tools"] == sorted(registered)
    assert overview["enabled_modules"] == sorted(MODULES)
    assert overview["existing_catalog_count"] == len(baseline)


@pytest.mark.parametrize("mode", ["modern", "legacy"])
@pytest.mark.parametrize("profile", list(MODULES) + [
    "core,incidents,risks,compliance,measures,personnel",
    "core,assets,isms,measures,risks", "core,reports",
])
def test_restricted_profiles_register_only_selected_modules_and_satisfied_dependencies(profile, mode, start_server):
    server = start_server(profile, mode)
    enabled = set(parse_modules(profile))
    baseline = json.loads(Path(__file__).with_name("fixtures").joinpath("tools_226.json").read_text())[mode]
    if not OPERATIONS:
        original = json.loads(Path(__file__).with_name("fixtures").joinpath("original_tools.json").read_text())[mode]
        baseline = {name: entry for name, entry in baseline.items() if name in original}
    expected = {
        name for name in baseline if tool_module(name) in enabled
        and DEPENDENCIES.get(canonical_name(name), frozenset()) <= enabled
    } | {"module_capabilities"}
    assert set(server.mcp.tools) == expected
    overview = server.mcp.tools["module_capabilities"]()
    assert overview["available_tool_count"] == len(expected)
    assert overview["enabled_modules"] == sorted(enabled)
    assert overview["available_tools"] == sorted(expected)


@pytest.mark.parametrize("name,params", [
    ("get_record", {"resource": "risks", "record_id": "not-even-a-valid-id"}),
    ("list_records", {"resource": "incidents"}),
    ("create_record", {"resource": "tasks", "payload_json": '{"subject":"Must not write"}'}),
    ("update_record", {"resource": "assets", "record_id": "x", "changes_json": '{"title":"x"}'}),
    ("bulk_create_records", {"resource": "measures", "items_json": '[{"title":"x"}]', "execute": True}),
    ("bulk_update_records", {"resource": "information-values", "items_json": '[]', "execute": True}),
    ("bulk_set_parent", {"resource": "business-processes", "items_json": '[]', "execute": True}),
])
@pytest.mark.parametrize("mode", ["modern", "legacy"])
def test_core_generic_tools_cannot_reach_disabled_resources(name, params, mode, start_server, monkeypatch):
    from v2_core import V2API
    monkeypatch.setattr(V2API, "from_env", staticmethod(lambda: pytest.fail("Disabled resource must not access credentials/HTTP")))
    server = start_server("core", mode)
    public = name if mode == "modern" else next(old for old, new in TOOL_NAME_MAP.items() if new == name)
    result = server.mcp.tools[public](**params)
    assert result["error_type"] == "module_disabled"
    assert result["tool"] == public


@pytest.mark.parametrize("lookup", list(LOOKUPS))
def test_lookup_guard_covers_every_legacy_lookup(lookup, start_server, monkeypatch):
    from v2_core import V2API
    monkeypatch.setattr(V2API, "from_env", staticmethod(lambda: pytest.fail("Disabled lookup must not access API")))
    server = start_server("core")
    result = server.mcp.tools["lookup_values"](lookup)
    assert result["error_type"] == "module_disabled"
    assert result["required_module"] == lookup_module(lookup)


def test_generic_guard_allows_enabled_resource_without_changing_result(start_server, monkeypatch):
    from v2_core import V2API
    class FakeAPI:
        def record(self, resource, record_id):
            assert resource == "risks"
            return {"data": {"id": record_id, "designation": "Offline"}}
    monkeypatch.setattr(V2API, "from_env", staticmethod(FakeAPI))
    server = start_server("core,risks")
    result = server.mcp.tools["get_record"]("risks", "offline-id")
    assert result == {"resource": "risks", "client_id": 12345,
                      "data": {"id": "offline-id", "designation": "Offline"}}
    assert "create_incident" not in server.mcp.tools
    assert "get_personnel" not in server.mcp.tools


def test_profile_is_immutable_after_startup(start_server, monkeypatch):
    server = start_server("core")
    monkeypatch.setenv("AUDATIS_MCP_MODULES", "all")
    assert server.mcp.tools["module_capabilities"]()["enabled_modules"] == ["core"]
    result = server.mcp.tools["list_records"]("risks")
    assert result["error_type"] == "module_disabled"
    assert "get_incident" not in server.mcp.tools


def test_cross_module_analyses_are_hidden_until_all_dependencies_enabled(start_server):
    server = start_server("core,assets,isms,measures")
    tools = server.mcp.tools
    assert "documentation_gaps" in tools
    assert "relationship_graph" not in tools
    assert "related_records" not in tools
    assert "inventory_snapshot" not in tools
    overview = tools["module_capabilities"]()
    assert overview["blocked_dependencies"]["relationship_graph"] == ["risks"]
    assert set(overview["blocked_dependencies"]["inventory_snapshot"]) == {"tasks", "incidents", "risks"}


def test_unknown_tools_fail_closed_without_registration():
    class Stub:
        def tool(self):
            pytest.fail("Unknown tool must not be registered")
    registry = ModuleRegistry(Stub(), "core")
    def new_unmapped_tool():
        return {}
    with pytest.raises(ValueError, match="Modulzuordnung"):
        registry.tool()(new_unmapped_tool)


def test_overview_is_offline_without_tokens(start_server, monkeypatch):
    from v2_core import V2API
    monkeypatch.setattr(V2API, "from_env", staticmethod(lambda: pytest.fail("No API for module discovery")))
    overview = start_server("risks").mcp.tools["module_capabilities"]()
    assert overview["available_tool_count"] == (6 if OPERATIONS else 2)
    assert overview["modules"]["personnel"]["enabled"] is False


def test_restricted_sdk_registration_preserves_schemas_without_stdio():
    # Exercise the real SDK independently of the server import stub.
    import asyncio
    from mcp.server import MCPServer
    from management_register import register_management_tools
    sdk = MCPServer("offline-profile-test")
    registry = ModuleRegistry(sdk, "risks")
    register_management_tools(registry)
    registry.finish()
    tools = sdk.list_tools()
    if inspect.isawaitable(tools):
        tools = asyncio.run(tools)
    expected = {"module_capabilities"}
    if OPERATIONS:
        expected |= {"query_risks", "get_risk", "list_risk_types", "list_risk_statuses"}
    assert {tool.name for tool in tools} == expected
    for tool in tools:
        assert tool.input_schema["type"] == "object"


def test_real_sdk_calls_cannot_bypass_generic_guard(monkeypatch):
    import asyncio
    from mcp.server import MCPServer
    from mcp_naming import named_mcp
    from v2_register import register_v2_tools
    from v2_core import V2API
    monkeypatch.setenv("AUDATIS_MCP_TOOL_NAMES", "modern")
    monkeypatch.setattr(V2API, "from_env", staticmethod(lambda: pytest.fail("No credentials or HTTP")))
    sdk = MCPServer("offline-generic-guard-test")
    registry = ModuleRegistry(sdk, "core")
    register_v2_tools(named_mcp(registry))
    registry.finish()
    result = sdk.call_tool("get_record", {"resource": "incidents", "record_id": "invalid"})
    if inspect.isawaitable(result):
        result = asyncio.run(result)
    assert json.loads(result.content[0].text)["error_type"] == "module_disabled"


def test_dotenv_selection_and_process_environment_precedence(tmp_path, start_server, monkeypatch):
    from dotenv.main import load_dotenv
    env_file = tmp_path / "profile.env"
    env_file.write_text("AUDATIS_MCP_MODULES=risks\n")
    monkeypatch.setattr("dotenv.load_dotenv", lambda path, override=False: load_dotenv(env_file, override=override))
    server = start_server(None)
    assert server.mcp.tools["module_capabilities"]()["enabled_modules"] == ["risks"]
    server = start_server("core")
    assert server.mcp.tools["module_capabilities"]()["enabled_modules"] == ["core"]


def test_profiles_preserve_preview_and_existing_write_resource_restrictions(start_server, monkeypatch):
    if not OPERATIONS:
        pytest.skip("Requires an authorized local management catalog")
    from management_core import ManagementAPI
    from v2_core import V2API
    monkeypatch.setattr(ManagementAPI, "from_env", staticmethod(lambda: pytest.fail("Preview cannot access API")))
    monkeypatch.setattr(V2API, "from_env", staticmethod(lambda: pytest.fail("Risks must remain GET-only")))
    server = start_server("core,incidents,risks")
    preview = server.mcp.tools["create_incident"](payload_json='{"title":"Offline","description":"Test"}')
    assert preview["mode"] == "preview" and preview["will_write"] is False
    rejected = server.mcp.tools["create_record"]("risks", '{"designation":"Not writable"}')
    assert rejected["error_type"] == "validation_error"
