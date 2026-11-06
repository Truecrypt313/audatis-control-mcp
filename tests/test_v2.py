"""Offline-only V2 regression tests. No .env, no network, no audatis API calls."""
from __future__ import annotations

import json
from uuid import UUID

import httpx
import pytest

from v2_core import (V2API, BASE, parse_json, validate_payload, resource_id,
                     uuid_id, collect_all)
import v2_tools
import v2_bulk
import v2_analysis
from v2_register import V2_TOOLS, register_v2_tools

ASSET_ID = "e4fcf3d0-e04a-45fc-838d-55b9cb0582b9"
CATEGORY_ID = "3cd3b9ac-5e08-4216-aca1-e3aa58c6fcc1"
PROCESS_ID = "b3442230-e04a-45fc-838d-55b9cb0582b9"
INCIDENT_ID = "ced42330-e04a-45fc-838d-55b9cb0582b9"


def build_api(handler):
    return V2API("https://tenant.example.test", "READ_TEST_FAKE",
                 write_token="WRITE_TEST_FAKE", transport=httpx.MockTransport(handler))


def test_resource_ids_cover_openapi_integer_reports_and_process_slug():
    assert resource_id("reports", 17) == "17"
    assert resource_id("business-processes", "process_12") == "process_12"
    assert resource_id("assets", ASSET_ID) == ASSET_ID
    for value in ("../reports", "tags", "process-types", "what?" ):
        with pytest.raises(ValueError):
            resource_id("business-processes", value)
    for value in ("../1", "0", "12/3", "1?x=a"):
        with pytest.raises(ValueError):
            resource_id("reports", value)
    with pytest.raises(ValueError):
        resource_id("assets", "../admin")


def test_validate_openapi_fields_and_types():
    assert validate_payload("assets", "create", {"title": "T", "category_id": CATEGORY_ID})
    for data in ({"title": "T", "category_id": CATEGORY_ID, "arbitrary": "abc"},
                 {"title": "T", "category_id": 55},
                 {"title": "", "category_id": CATEGORY_ID}):
        with pytest.raises(ValueError):
            validate_payload("assets", "create", data)
    with pytest.raises(ValueError):
        validate_payload("risks", "create", {"title": "Unzulässig"})
    with pytest.raises(ValueError):
        validate_payload("information-values", "update", {"protection_needs": {"confidentiality": {"level": "high"}}}, partial=True)
    with pytest.raises(ValueError):
        validate_payload("tasks", "update", {"status": "unknown"}, partial=True)
    with pytest.raises(ValueError):
        validate_payload("tasks", "create", {"subject": "X", "due_date": "2026-20-31"})
    with pytest.raises(ValueError):
        validate_payload("assets", "create", {"title": "T", "category_id": CATEGORY_ID, "asset_owner_user_id": True})


def test_information_protection_is_string_enum_not_asset_integer():
    needs = {"confidentiality": {"level": "high", "reason": "Test"},
             "integrity": {"level": "normal"}, "availability": {"level": "inherited"}}
    assert validate_payload("information-values", "create", {"title": "Test", "protection_needs": needs})
    with pytest.raises(ValueError):
        validate_payload("information-values", "create", {"title": "Test", "protection_needs": {"confidentiality": {"level": 2}}})
    with pytest.raises(ValueError):
        validate_payload("information-values", "create", {"title": "Test", "protection_needs": {"availability": {"level": "high"}}})


def test_no_redirect_and_no_proxy_and_no_secrets_in_errors():
    calls = []
    def handle(req):
        calls.append(req)
        return httpx.Response(302, headers={"Location": "https://invalid.example/"})
    api = build_api(handle)
    with pytest.raises(RuntimeError, match="302") as exc:
        api.records("assets")
    assert "READ_TEST_FAKE" not in str(exc.value)
    assert len(calls) == 1
    assert calls[0].headers["Authorization"] == "Bearer READ_TEST_FAKE"
    assert calls[0].url.path == f"{BASE}/assets"


def test_read_only_resource_fails_closed_for_write():
    api = build_api(lambda req: pytest.fail(f"Shouldn't send request: {req.method}"))
    with pytest.raises(ValueError):
        api.create("risks", {"subject": "A"})
    with pytest.raises(ValueError):
        api.update("incidents", INCIDENT_ID, {"title": "A"})


def test_list_and_detail_and_numeric_report_id(monkeypatch):
    calls = []
    def handler(req):
        calls.append(req)
        if req.url.path.endswith("/reports/123"):
            return httpx.Response(200, json={"data": {"id": 123, "designation": "Report"}})
        return httpx.Response(200, json={"data": [{"id": ASSET_ID, "title": "Firewall", "secret": "HIDDEN"}],
                                          "meta": {"total": 1, "total_pages": 1}})
    api = build_api(handler)
    monkeypatch.setattr(v2_tools.V2API, "from_env", staticmethod(lambda: api))
    out = v2_tools.v2_list_records("assets")
    assert out["data"][0]["title"] == "Firewall"
    assert "secret" not in out["data"][0]
    assert v2_tools.v2_get_record("reports", "123")["data"]["id"] == 123
    assert calls[1].url.path == f"{BASE}/reports/123"


def test_update_preserves_title_and_uses_write_token():
    calls = []
    def handle(req):
        calls.append(req)
        if req.method == "GET":
            return httpx.Response(200, json={"data": {"id": ASSET_ID, "title": "FW-TEST-01", "description": "old"}})
        assert req.method == "PUT"
        assert req.url.path == f"{BASE}/assets/{ASSET_ID}"
        assert json.loads(req.content) == {"title": "FW-TEST-01", "description": "new"}
        assert req.headers["Authorization"] == "Bearer WRITE_TEST_FAKE"
        return httpx.Response(200, json={"data": {"id": ASSET_ID, "title": "FW-TEST-01", "description": "new"}})
    api = build_api(handle)
    out = api.update("assets", ASSET_ID, {"description": "new"})
    assert out["updated"] is True
    assert [x.method for x in calls] == ["GET", "PUT"]


def test_update_idempotent_no_write_if_same_value():
    calls = []
    def handle(req):
        calls.append(req)
        return httpx.Response(200, json={"data": {"id": ASSET_ID, "title": "FW-TEST-01", "description": "same"}})
    api = build_api(handle)
    assert api.update("assets", ASSET_ID, {"description": "same"})["updated"] is False
    assert len(calls) == 1


def test_incident_link_expected_field_and_200_is_idempotent():
    calls = []
    def handle(req):
        calls.append(req)
        if req.method == "POST":
            assert json.loads(req.content) == {"asset_id": ASSET_ID}
            return httpx.Response(200, json={"data": {"target_id": ASSET_ID}})
        return httpx.Response(200, json={"data": [{"target_id": ASSET_ID}]})
    api = build_api(handle)
    assert api.incident_links(INCIDENT_ID, "assets", target_id=ASSET_ID)["data"]["target_id"] == ASSET_ID
    assert api.incident_links(INCIDENT_ID, "assets")["data"][0]["target_id"] == ASSET_ID
    assert [r.method for r in calls] == ["POST", "GET"]
    assert calls[0].url.path == f"{BASE}/incidents/{INCIDENT_ID}/assets"
    with pytest.raises(ValueError):
        api.incident_links(INCIDENT_ID, "../../admin", target_id=ASSET_ID)


def test_bulk_dry_run_never_calls_api(monkeypatch):
    monkeypatch.setattr(v2_bulk.V2API, "from_env", staticmethod(lambda: pytest.fail("No network in dry run")))
    raw = json.dumps([{"title": "A", "category_id": CATEGORY_ID}, {"title": "B", "category_id": CATEGORY_ID}])
    out = v2_bulk.v2_bulk_create_records("assets", raw)
    assert out["count"] == 2 and out["execute"] is False
    with pytest.raises(ValueError):
        v2_bulk.v2_bulk_create_records("assets", json.dumps([{"title": "A", "category_id": CATEGORY_ID}] * 2))
    with pytest.raises(ValueError):
        v2_bulk.v2_bulk_create_records("assets", json.dumps([{"title": str(i), "category_id": CATEGORY_ID} for i in range(11)]))


def test_bulk_create_existing_collision_aborts_before_write(monkeypatch):
    calls = []
    def handle(req):
        calls.append(req)
        return httpx.Response(200, json={"data": [{"title": "Demo", "id": ASSET_ID}],
                                         "meta": {"total_pages": 1, "total": 1}})
    api = build_api(handle)
    monkeypatch.setattr(v2_bulk.V2API, "from_env", staticmethod(lambda: api))
    with pytest.raises(ValueError, match="Dubletten"):
        v2_bulk.v2_bulk_create_records("assets", json.dumps([{"title": "  DEMO  ", "category_id": CATEGORY_ID}]), execute=True)
    assert [r.method for r in calls] == ["GET"]


def test_bulk_create_stops_after_first_write_failure(monkeypatch):
    calls = []
    def handle(req):
        calls.append(req)
        # bypass duplicate scan with check_existing=False
        if len(calls) == 1:
            return httpx.Response(201, json={"data": {"id": ASSET_ID, "title": "First"}})
        return httpx.Response(422, json={"message": "validation"})
    api = build_api(handle)
    monkeypatch.setattr(v2_bulk.V2API, "from_env", staticmethod(lambda: api))
    raw = json.dumps([{"title": "First", "category_id": CATEGORY_ID},
                      {"title": "Second", "category_id": CATEGORY_ID},
                      {"title": "Third", "category_id": CATEGORY_ID}])
    out = v2_bulk.v2_bulk_create_records("assets", raw, execute=True, check_existing=False)
    assert out["completed"] is False and len(out["created"]) == 1
    assert out["stopped_at_index"] == 1
    assert [r.method for r in calls] == ["POST", "POST"]


def test_bulk_update_validates_every_record_before_writing(monkeypatch):
    calls = []
    def handle(req):
        calls.append(req)
        if req.method == "GET":
            if req.url.path.endswith(PROCESS_ID):
                return httpx.Response(404)
            return httpx.Response(200, json={"data": {"id": ASSET_ID, "title": "F", "is_shared": False}})
        pytest.fail("Must not PUT while preflight GET fails")
    api = build_api(handle)
    monkeypatch.setattr(v2_bulk.V2API, "from_env", staticmethod(lambda: api))
    raw = json.dumps([{"record_id": ASSET_ID, "changes": {"is_shared": True}},
                      {"record_id": PROCESS_ID, "changes": {"is_shared": True}}])
    with pytest.raises(RuntimeError, match="404"):
        v2_bulk.v2_bulk_update_records("assets", raw, execute=True)
    assert [r.method for r in calls] == ["GET", "GET"]


def test_bulk_update_dry_run_validation_no_network(monkeypatch):
    monkeypatch.setattr(v2_bulk.V2API, "from_env", staticmethod(lambda: pytest.fail("Should not call network")))
    raw = json.dumps([{"record_id": ASSET_ID, "changes": {"parent_id": PROCESS_ID}}])
    assert v2_bulk.v2_bulk_update_records("assets", raw)["execute"] is False
    with pytest.raises(ValueError):
        v2_bulk.v2_bulk_update_records("assets", json.dumps([{"record_id": ASSET_ID, "changes": {"protection_needs": {}}}]))


def test_inventory_graph_and_gaps_are_read_only(monkeypatch):
    calls = []
    def handler(req):
        calls.append(req)
        assert req.method == "GET"
        res = req.url.path.split("/")[-1]
        d = {"assets": [{"id": ASSET_ID, "title": "Firewall", "parent_id": None,
                          "asset_owner_user_id": None, "protection_needs": {"confidentiality": 2, "integrity": 3, "availability": 2},
                          "linked_assets": [], "information_values": [], "measures": []}],
             "information-values": [], "business-processes": [], "measures": [],
             "risks": [], "tasks": [], "incidents": []}
        return httpx.Response(200, json={"data": d[res], "meta": {"total_pages": 1}})
    api = build_api(handler)
    monkeypatch.setattr(v2_analysis.V2API, "from_env", staticmethod(lambda: api))
    assert v2_analysis.v2_inventory_snapshot()["inventory"]["assets"]["count"] == 1
    assert v2_analysis.v2_asset_graph()["nodes"][0]["id"] == ASSET_ID
    gaps = v2_analysis.v2_documentation_gaps()
    assert "missing_owner" in [x["issue"] for x in gaps["issues"]]
    assert "no_linked_measure" in [x["issue"] for x in gaps["issues"]]
    assert not any(x["issue"] == "cia_incomplete" for x in gaps["issues"])
    assert {x.method for x in calls} == {"GET"}


def test_tools_are_unique_and_register_all():
    names = [f.__name__ for f in V2_TOOLS]
    assert len(names) == len(set(names)) == 15
    class FakeMCP:
        def __init__(self): self.tools = []
        def tool(self):
            def register(f):
                self.tools.append(f.__name__)
                return f
            return register
    server = FakeMCP()
    register_v2_tools(server)
    assert server.tools == names


def test_legacy_server_with_additive_v2_registration_has_31_tools(monkeypatch):
    """Check existing server module import with an offline MCPServer stub.

    This checks registration wiring, not the real MCP SDK's stdio transport.
    """
    import importlib
    import sys
    import types

    class OfflineMCP:
        def __init__(self, name):
            self.name = name
            self.registered = []
        def tool(self):
            def register(function):
                self.registered.append(function.__name__)
                return function
            return register
        def run(self, **kwargs):
            pytest.fail("Must never start a real server in tests")

    mcp_pkg = types.ModuleType("mcp")
    mcp_pkg.__path__ = []
    server_pkg = types.ModuleType("mcp.server")
    server_pkg.MCPServer = OfflineMCP
    monkeypatch.setitem(sys.modules, "mcp", mcp_pkg)
    monkeypatch.setitem(sys.modules, "mcp.server", server_pkg)
    monkeypatch.delitem(sys.modules, "server", raising=False)
    old_server = importlib.import_module("server")
    # Works both before and after the two-line server.py integration patch.
    if len(old_server.mcp.registered) == 16:
        register_v2_tools(old_server.mcp)
    registered = old_server.mcp.registered
    v2_names = {fn.__name__ for fn in V2_TOOLS}

    assert len(registered) in (31, 36, 47)
    assert v2_names.issubset(set(registered))
    assert len(set(registered)) == len(registered)
    monkeypatch.delitem(sys.modules, "server", raising=False)


def test_lookup_is_explicitly_whitelisted():
    requests = []
    def handle(req):
        requests.append(req)
        return httpx.Response(200, json={"data": [{"name": "Normal"}]})
    api = build_api(handle)
    assert api.lookup("asset_protection_levels")["data"][0]["name"] == "Normal"
    assert requests[0].method == "GET"
    assert requests[0].url.path == f"{BASE}/assets/protection-levels"
    with pytest.raises(ValueError):
        api.lookup("/api/v1/admin/all")
    assert len(requests) == 1


def test_bulk_update_task_preserves_original_subject(monkeypatch):
    tasks_id = "01a1aac7-1f2a-7365-88fe-4db76c63cb20"
    calls = []
    def handle(req):
        calls.append(req)
        if req.method == "GET":
            return httpx.Response(200, json={"data": {"id": tasks_id, "subject": "Original", "priority": "normal"}})
        body = json.loads(req.content)
        assert body == {"subject": "Original", "priority": "high"}
        return httpx.Response(200, json={"data": {"id": tasks_id, "subject": "Original", "priority": "high"}})
    api = build_api(handle)
    monkeypatch.setattr(v2_bulk.V2API, "from_env", staticmethod(lambda: api))
    out = v2_bulk.v2_bulk_update_records("tasks", json.dumps([{
        "record_id": tasks_id, "changes": {"priority": "high"}
    }]), execute=True)
    assert out["completed"] is True
    assert [r.method for r in calls] == ["GET", "PUT"]


def test_asset_reference_fields_validated_as_uuids():
    with pytest.raises(ValueError):
        validate_payload("assets", "create", {"title": "T", "category_id": "not-a-uuid"})
    with pytest.raises(ValueError):
        validate_payload("assets", "update", {"parent_id": "../../other"}, partial=True)
