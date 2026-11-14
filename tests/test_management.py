"""Official contract, compatibility and transport tests; httpx.MockTransport only."""
from __future__ import annotations

import base64
import importlib
import inspect
import json
import logging
import sys
import types
from pathlib import Path

import httpx
import pytest

import management_core as core
from management_catalog import OPERATIONS, SPEC, load_spec
from management_register import register_management_tools
from management_tools import MANAGEMENT_TOOLS, describe_management_tool

pytestmark = pytest.mark.skipif(len(OPERATIONS) != 177,
                               reason="Requires a separately supplied authorized vendor contract")
UID = "00000000-0000-0000-0000-0000000003ed"
BASE = "/api/v1/clients/12345"


def sample(schema):
    if "anyOf" in schema:
        return sample(next(s for s in schema["anyOf"] if s.get("type") != "null"))
    if "enum" in schema:
        return schema["enum"][0]
    kind = schema.get("type")
    if kind == "object":
        return {key: sample(schema["properties"][key]) for key in schema.get("required", [])}
    if kind == "array":
        return [sample(schema["items"])] * schema.get("minItems", 0)
    if kind in ("integer", "number"):
        return schema.get("minimum", 1)
    if kind == "boolean":
        return False
    if schema.get("format") == "uuid":
        return UID
    if schema.get("format") == "date":
        return "2026-11-14"
    if schema.get("format") == "date-time":
        return "2026-11-14T12:00:00+01:00"
    if schema.get("format") == "email":
        return "offline@example.test"
    if schema.get("pattern", "").startswith("^(gdpr_art33_initial"):
        return "gdpr_art33_initial"
    return "Offline test"


def arguments(name):
    op = OPERATIONS[name]
    path = {}
    for p in op["parameters"]:
        if p["in"] == "path" and p["name"] != "mid":
            schema = p["schema"]
            path[p["name"]] = 7 if schema["type"] == "integer" else UID if schema.get("format") == "uuid" else "record-1"
    media, schema = core.body_schema(op)
    payload = sample(schema) if schema is not None else None
    if op["method"] == "PUT" and payload == {}:
        key = next(iter(schema["properties"]))
        payload[key] = sample(schema["properties"][key])
    extra = {}
    if media == "multipart/form-data":
        payload.pop("file", None)
        extra = {"file_name": "evidence.txt", "file_base64": base64.b64encode(b"offline evidence").decode()}
    return {"path_params_json": json.dumps(path),
            "payload_json": json.dumps(payload) if payload is not None else "", **extra}


def mock_api(handler):
    return core.ManagementAPI("https://audatis.example.test", "READ_FAKE",
                              write_token="WRITE_FAKE", transport=httpx.MockTransport(handler))


@pytest.mark.parametrize("name", list(OPERATIONS))
def test_every_official_operation_uses_exact_path_method_schema_and_status(name, monkeypatch):
    op = OPERATIONS[name]
    calls = []
    status = next(int(s) for s in op["responses"] if s.startswith("2"))
    binary = name == "download_incident_document"

    def handle(req):
        calls.append(req)
        assert req.method == op["method"]
        assert req.url.host == "audatis.example.test"
        if "{mid}" in op["path"]:
            assert req.url.path.startswith(BASE + "/") or req.url.path == BASE
        expected_token = "READ_FAKE" if op["method"] == "GET" else "WRITE_FAKE"
        assert req.headers["Authorization"] == "Bearer " + expected_token
        assert req.headers["X-Request-ID"]
        if binary:
            return httpx.Response(status, content=b"offline file", headers={"Content-Type": "application/octet-stream"})
        if status == 204:
            return httpx.Response(204)
        return httpx.Response(status, json={"data": {"id": 7}, "meta": {"total_pages": 1}})

    api = mock_api(handle)
    monkeypatch.setattr(core.ManagementAPI, "from_env", staticmethod(lambda: api))
    result = core.run_operation(name, **arguments(name), execute=True,
                                acknowledge_side_effects=True, confirm_delete=True)
    assert result["ok"]
    assert result["http_status"] == status
    assert len(calls) == 1  # Never a preflight/write retry or automatic link traversal.
    values = json.loads(arguments(name)["path_params_json"])
    expected = op["path"].replace("{mid}", "12345")
    for key, value in values.items():
        expected = expected.replace("{" + key + "}", str(value))
    assert calls[0].url.path == expected
    if binary:
        assert base64.b64decode(result["content_base64"]) == b"offline file"
        assert calls[0].headers["Accept"] == "application/octet-stream"
    elif status == 204:
        assert result["deleted"]
    if core.body_schema(op)[0] == "multipart/form-data":
        assert "multipart/form-data" in calls[0].headers["Content-Type"]
        assert b"offline evidence" in calls[0].content
    elif arguments(name)["payload_json"]:
        assert json.loads(calls[0].content) == json.loads(arguments(name)["payload_json"])
    else:
        assert calls[0].content == b""


@pytest.mark.parametrize("name", [n for n, op in OPERATIONS.items() if op["method"] != "GET"])
def test_every_mutation_defaults_to_local_preview_without_credentials(name, monkeypatch):
    monkeypatch.setattr(core.ManagementAPI, "from_env", staticmethod(
        lambda: pytest.fail("Preview must not load credentials or send HTTP")))
    result = core.run_operation(name, **arguments(name))
    assert result["mode"] == "preview"
    assert result["will_write"] is False


def test_schema_metadata_complete_and_old_contracts_not_expanded():
    assert len(OPERATIONS) == 177
    assert len(MANAGEMENT_TOOLS) == 179
    assert SPEC["info"]["version"] == "1.3.1"
    for name, op in OPERATIONS.items():
        assert describe_management_tool(name)["method"] == op["method"]
    from v2_core import WRITE_RESOURCES, LOOKUPS
    assert "risks" not in WRITE_RESOURCES
    assert "incidents" not in WRITE_RESOURCES
    assert "risk_statuses" not in LOOKUPS


@pytest.mark.parametrize("mode", ["legacy", "modern"])
def test_all_47_original_names_signatures_descriptions_are_unchanged(mode, monkeypatch):
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
            pytest.fail("No stdio")
    package = types.ModuleType("mcp")
    package.__path__ = []
    server_package = types.ModuleType("mcp.server")
    server_package.MCPServer = OfflineMCP
    monkeypatch.setitem(sys.modules, "mcp", package)
    monkeypatch.setitem(sys.modules, "mcp.server", server_package)
    monkeypatch.setenv("AUDATIS_MCP_TOOL_NAMES", mode)
    monkeypatch.delitem(sys.modules, "server", raising=False)
    try:
        server = importlib.import_module("server")
        golden = json.loads(Path(__file__).with_name("fixtures").joinpath("original_tools.json").read_text())[mode]
        assert len(server.mcp.tools) == 227
        assert len(golden) == 47
        for name, before in golden.items():
            fn = server.mcp.tools[name]
            assert str(inspect.signature(fn)) == before["signature"]
            assert fn.__doc__ == before["description"]
        new = set(server.mcp.tools) - set(golden)
        assert new == {f.__name__ for f in MANAGEMENT_TOOLS} | {"module_capabilities"}
        assert all(not n.startswith(("v2_", "v21_")) for n in new)
    finally:
        monkeypatch.delitem(sys.modules, "server", raising=False)


@pytest.mark.parametrize("name,kwargs", [
    ("get_incident", {"path_params_json": '{"pid":"../users"}'}),
    ("get_incident", {"path_params_json": '{"pid":"https://evil.test"}'}),
    ("get_incident", {"path_params_json": '{"pid":"' + UID + '","mid":42}'}),
    ("get_compliance_register", {"path_params_json": '{"cpid":true}'}),
    ("get_compliance_register", {"path_params_json": '{"cpid":-1}'}),
    ("get_compliance_register", {"path_params_json": '{"cpid":"7"}'}),
    ("query_incidents", {"query_json": '{"per_page":201}'}),
    ("query_incidents", {"query_json": '{"page":0}'}),
    ("query_incidents", {"query_json": '{"archived":"yes"}'}),
    ("query_risks", {"query_json": '{"url":"https://evil.test"}'}),
    ("create_incident", {"payload_json": '{"title":"x","description":"x","status_code":"closed"}'}),
    ("create_incident", {"payload_json": '{"title":"x","description":"x","reporter":{"email":"bad"}}'}),
    ("create_incident", {"payload_json": '{"title":"x","description":"x","reporter":{"unknown":1}}'}),
    ("update_incident", {"path_params_json": '{"pid":"' + UID + '"}', "payload_json": '{}'}),
    ("create_measure", {"payload_json": '{"title":"x","monitoring":{}}'}),
    ("create_measure", {"payload_json": '{"title":"x","asset_ids":[]}'}),
    ("update_measure", {"path_params_json": '{"pid":"' + UID + '"}', "payload_json": '{"description":"x"}'}),
    ("query_audit_log", {"query_json": '{"action":"archive"}'}),
    ("query_audit_log", {"query_json": '{"from":"2026-02-30T10:00:00"}'}),
    ("query_risks", {"query_json": '{"page":1,"page":2}'}),
    ("create_measure", {"payload_json": '{"title":NaN}'}),
])
def test_invalid_inputs_fail_before_any_network_or_token_access(name, kwargs, monkeypatch):
    monkeypatch.setattr(core.ManagementAPI, "from_env", staticmethod(
        lambda: pytest.fail("Invalid input must not access API")))
    with pytest.raises(ValueError):
        core.run_operation(name, **kwargs)


def test_write_acknowledgement_and_delete_confirmation(monkeypatch):
    monkeypatch.setattr(core.ManagementAPI, "from_env", staticmethod(lambda: pytest.fail("No API")))
    with pytest.raises(ValueError, match="acknowledge_side_effects"):
        core.run_operation("create_incident", payload_json='{"title":"x","description":"y"}', execute=True)
    with pytest.raises(ValueError, match="confirm_delete"):
        core.run_operation("delete_measure", path_params_json=json.dumps({"pid": UID}), execute=True)
    with pytest.raises(ValueError, match="Boolean"):
        core.run_operation("create_measure", payload_json='{"title":"x"}', execute="true")


@pytest.mark.parametrize("status", [302, 401, 403, 404, 409, 422, 429, 500])
def test_errors_redacted_and_no_redirect_or_retry(status, monkeypatch, caplog):
    calls = []
    def handle(req):
        calls.append(req)
        return httpx.Response(status, headers={"Location": "https://evil.test/"},
                              json={"error": {"message": "SECRET_SERVER_CONTENT"}})
    monkeypatch.setattr(core.ManagementAPI, "from_env", staticmethod(lambda: mock_api(handle)))
    with caplog.at_level(logging.INFO, logger="audatis.management"):
        with pytest.raises(RuntimeError) as exc:
            core.run_operation("create_measure", payload_json='{"title":"PRIVATE_PAYLOAD"}', execute=True)
    assert len(calls) == 1
    output = str(exc.value) + caplog.text
    for secret in ("SECRET_SERVER_CONTENT", "PRIVATE_PAYLOAD", "READ_FAKE", "WRITE_FAKE"):
        assert secret not in output
    assert f"HTTP {status}" in str(exc.value)


def test_network_error_is_uncertain_and_not_retried(monkeypatch):
    calls = []
    def handle(req):
        calls.append(req)
        raise httpx.ReadTimeout("SECRET_EXCEPTION", request=req)
    monkeypatch.setattr(core.ManagementAPI, "from_env", staticmethod(lambda: mock_api(handle)))
    with pytest.raises(RuntimeError, match="ungewiss") as exc:
        core.run_operation("create_measure", payload_json='{"title":"x"}', execute=True)
    assert "SECRET_EXCEPTION" not in str(exc.value)
    assert len(calls) == 1


@pytest.mark.parametrize("response", [
    httpx.Response(200, text="<html>login</html>"),
    httpx.Response(200, content=b"{", headers={"Content-Type": "application/json"}),
    httpx.Response(200, json=[]),
    httpx.Response(200, json={"unexpected": "shape"}),
])
def test_malformed_success_is_not_reported_as_success(response, monkeypatch):
    monkeypatch.setattr(core.ManagementAPI, "from_env", staticmethod(lambda: mock_api(lambda _: response)))
    with pytest.raises(RuntimeError):
        core.run_operation("query_risks")


def test_query_encoding_pagination_metadata_and_no_auto_traversal(monkeypatch):
    calls = []
    def handle(req):
        calls.append(req)
        assert req.url.params["from"] == "2026-11-01T10:00:00+01:00"
        assert b"%2B01" in req.url.query
        assert req.url.params["page"] == "2"
        return httpx.Response(200, json={"data": [], "meta": {"page": 2, "total_pages": 3},
                                       "_links": {"next": "https://evil.test/"}})
    monkeypatch.setattr(core.ManagementAPI, "from_env", staticmethod(lambda: mock_api(handle)))
    result = core.run_operation("query_audit_log", query_json=json.dumps({
        "from": "2026-11-01T10:00:00+01:00", "page": 2, "per_page": 200}))
    assert result["response"]["meta"]["total_pages"] == 3
    assert len(calls) == 1


def test_null_and_required_update_fields_preserved_without_invented_get_preflight(monkeypatch):
    def handle(req):
        assert req.method == "PUT"
        assert json.loads(req.content) == {"title": "Existing", "status": 0,
                                         "is_relevant": False, "responsible_user_id": None}
        return httpx.Response(200, json={"data": {"id": 7}})
    monkeypatch.setattr(core.ManagementAPI, "from_env", staticmethod(lambda: mock_api(handle)))
    core.run_operation("update_compliance_register", path_params_json='{"cpid":7}',
                       payload_json='{"title":"Existing","status":0,"is_relevant":false,"responsible_user_id":null}',
                       execute=True)


@pytest.mark.parametrize("filename,content", [
    ("../secret", "YQ=="), ("a\n.txt", "YQ=="), ("a.txt", "not base64"),
    ("a.txt", ""), ("x" * 151, "YQ=="),
])
def test_upload_invalid_input_is_local(filename, content):
    with pytest.raises(ValueError):
        core.run_operation("upload_incident_document", path_params_json=json.dumps({"pid": UID}),
                           file_name=filename, file_base64=content)


def test_upload_size_limit_and_streamed_response_limit(monkeypatch):
    monkeypatch.setattr(core, "MAX_FILE", 2)
    with pytest.raises(ValueError):
        core.run_operation("upload_incident_document", path_params_json=json.dumps({"pid": UID}),
                           file_name="a.txt", file_base64=base64.b64encode(b"123").decode())
    monkeypatch.setattr(core, "MAX_RESPONSE", 2)
    monkeypatch.setattr(core.ManagementAPI, "from_env", staticmethod(
        lambda: mock_api(lambda _: httpx.Response(200, json={"data": []}))))
    with pytest.raises(RuntimeError, match="Limit"):
        core.run_operation("query_risks")


def test_tenant_and_origin_guards_and_response_path_tampering():
    for origin in ("http://evil.test", "https://a.test/api", "https://user:pw@a.test"):
        with pytest.raises(RuntimeError):
            core.ManagementAPI(origin, "READ_FAKE")
    with pytest.raises(ValueError):
        core.ManagementAPI("https://a.test", "READ_FAKE", client_id=42)
    prepared = core.prepare("get_incident", json.dumps({"pid": UID}), "{}")
    prepared["path"] = prepared["path"].replace("12345", "42")
    with pytest.raises(ValueError):
        mock_api(lambda _: pytest.fail("No HTTP")).perform("get_incident", prepared)


def test_spec_hash_is_pinned(monkeypatch, tmp_path):
    bad = tmp_path / "bad.json"
    bad.write_text("{}")
    monkeypatch.setattr("management_catalog.SPEC_PATH", bad)
    with pytest.raises(RuntimeError, match="Prüfsumme"):
        load_spec()


def test_registration_errors_are_sanitized_and_keep_public_name():
    class Registry:
        def __init__(self):
            self.tools = {}
        def tool(self):
            def reg(fn):
                self.tools[fn.__name__] = fn
                return fn
            return reg
    mcp = Registry()
    register_management_tools(mcp)
    out = mcp.tools["create_measure"](payload_json='{"title":"PRIVATE","unknown":"SECRET"}')
    assert out["tool"] == "create_measure"
    assert out["error_type"] == "validation_error"
    assert "PRIVATE" not in str(out) and "SECRET" not in str(out)


def test_actual_sdk_builds_all_additive_tool_schemas_without_stdio_or_http():
    # No server.py import and no transport launch: exercise the installed MCP SDK.
    from mcp.server import MCPServer
    mcp = MCPServer("offline-management-test")
    register_management_tools(mcp)
    import asyncio
    tools = mcp.list_tools()
    if inspect.isawaitable(tools):
        tools = asyncio.run(tools)
    assert len(tools) == 179
    assert {t.name for t in tools} == {t.__name__ for t in MANAGEMENT_TOOLS}
    for tool in tools:
        schema = tool.input_schema
        assert schema["type"] == "object"
        json.dumps(schema)


@pytest.mark.parametrize("name", ["create_risk", "update_risk", "delete_risk",
                                  "create_audit", "create_isms_control", "link_measure_asset"])
def test_undocumented_operations_are_not_exposed(name):
    assert name not in OPERATIONS
    with pytest.raises(ValueError):
        core.run_operation(name)


def test_env_tenant_guard_is_inherited_without_loading_real_config(monkeypatch):
    from audatis_api import AudatisAPI
    original = AudatisAPI("https://audatis.example.test", "READ_FAKE", 12345)
    monkeypatch.setattr(AudatisAPI, "from_env", classmethod(lambda cls: original))
    monkeypatch.setenv("AUDATIS_CLIENT_ID", "42")
    with pytest.raises(RuntimeError, match="Mandant"):
        core.ManagementAPI.from_env()
    monkeypatch.setenv("AUDATIS_CLIENT_ID", "12345")
    api = core.ManagementAPI.from_env()
    assert isinstance(api, core.ManagementAPI)
    assert api.read_token == "READ_FAKE"
