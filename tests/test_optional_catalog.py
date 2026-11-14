"""Own minimal synthetic contract, not a reconstruction of the vendor's specification."""
from __future__ import annotations

import asyncio
import copy
import hashlib
import json
import os
import subprocess
import sys
from pathlib import Path

import httpx
import pytest

import management_catalog as catalog

ROOT = Path(__file__).resolve().parents[1]


def synthetic_spec():
    # Two hand-written examples exercise mechanics; not vendor contract coverage.
    tenant = {"name": "mid", "in": "path", "required": True, "schema": {"type": "integer"}}
    return {
        "openapi": "3.0.0", "info": {"version": "1.3.1", "title": "Synthetic unit-test catalog"},
        "components": {"schemas": {}},
        "paths": {
            "/api/v1/clients/{mid}/risks": {"parameters": [tenant], "get": {
                "operationId": "listRisks", "tags": ["Risks"],
                "summary": "Synthetic list operation",
                "parameters": [{"name": "page", "in": "query", "schema": {"type": "integer", "minimum": 1}}],
                "responses": {"200": {"description": "Synthetic response"}}}},
            "/api/v1/clients/{mid}/measures": {"parameters": [tenant], "post": {
                "operationId": "createMeasure", "tags": ["Measures"],
                "summary": "Synthetic mutation operation",
                "requestBody": {"required": True, "content": {"application/json": {"schema": {
                    "type": "object", "required": ["title"],
                    "properties": {"title": {"type": "string", "minLength": 1}}}}}},
                "responses": {"201": {"description": "Synthetic response"}}}},
        },
    }


def write_spec(path, spec):
    raw = json.dumps(spec).encode()
    path.write_bytes(raw)
    return hashlib.sha256(raw).hexdigest()


@pytest.fixture
def local_catalog(tmp_path, monkeypatch):
    path = tmp_path / "synthetic.json"
    sha = write_spec(path, synthetic_spec())
    with monkeypatch.context() as patch:
        patch.setenv("AUDATIS_OPENAPI_SPEC_PATH", str(path))
        patch.setenv("AUDATIS_OPENAPI_SPEC_SHA256", sha)
        catalog.get_catalog.cache_clear()
        yield path
    catalog.get_catalog.cache_clear()


def child(code, **settings):
    env = {k: v for k, v in os.environ.items() if not k.startswith("AUDATIS_")}
    env.update({"AUDATIS_MCP_MODULES": "all", "AUDATIS_MCP_TOOL_NAMES": "modern",
                "AUDATIS_OPENAPI_SPEC_PATH": "", "AUDATIS_ALLOWED_CLIENT_ID": "12345",
                "AUDATIS_CLIENT_ID": "0", "AUDATIS_BASE_URL": "https://api.demo.invalid",
                "AUDATIS_API_TOKEN": "OFFLINE_FAKE_ONLY", **settings})
    prefix = (
        "import dotenv,socket\n"
        "dotenv.load_dotenv=lambda *a,**k:False\n"
        "def blocked(*a,**k): raise RuntimeError('Offline test: no network')\n"
        "socket.socket.connect=blocked\nsocket.socket.connect_ex=blocked\n"
    )
    result = subprocess.run([sys.executable, "-c", prefix + code], env=env, cwd=ROOT,
                            capture_output=True, text=True, timeout=30)
    assert result.returncode == 0, result.stderr
    return json.loads(result.stdout)


LIST_TOOLS = (
    "import asyncio,json,server\n"
    "from management_catalog import catalog_status\n"
    "tools=asyncio.run(server.mcp.list_tools())\n"
    "print(json.dumps({'names':[t.name for t in tools],'catalog':catalog_status()}))\n"
)


def test_import_is_lazy_even_with_configured_path():
    result = child(
        "from pathlib import Path\n"
        "def forbidden(*a,**k): raise AssertionError('Import read specification')\n"
        "Path.read_bytes=forbidden\n"
        "import management_catalog,json\n"
        "print(json.dumps(management_catalog.get_catalog.cache_info().currsize))\n",
        AUDATIS_OPENAPI_SPEC_PATH="do-not-read.json",
    )
    assert result == 0


@pytest.mark.parametrize("mode", ["modern", "legacy"])
@pytest.mark.parametrize("source,status", [("", "disabled"), ("absent-contract.json", "missing")])
def test_baseline_starts_without_specification_and_preserves_47_names(mode, source, status):
    result = child(LIST_TOOLS, AUDATIS_OPENAPI_SPEC_PATH=source, AUDATIS_MCP_TOOL_NAMES=mode)
    golden = json.loads((ROOT / "tests/fixtures/original_tools.json").read_text())[mode]
    assert set(result["names"]) == set(golden) | {"module_capabilities"}
    assert len(result["names"]) == 48
    assert result["catalog"]["status"] == status
    assert result["catalog"]["operation_count"] == 0


def test_synthetic_optional_catalog_registers_only_its_two_operations(local_catalog):
    result = child(LIST_TOOLS, AUDATIS_OPENAPI_SPEC_PATH=str(local_catalog),
                   AUDATIS_OPENAPI_SPEC_SHA256=hashlib.sha256(local_catalog.read_bytes()).hexdigest())
    assert len(result["names"]) == 52
    assert {"query_risks", "create_measure", "management_capabilities",
            "describe_management_tool"} <= set(result["names"])
    assert result["catalog"]["operation_count"] == 2
    assert "create_incident" not in result["names"]


@pytest.mark.parametrize("mode", ["legacy", "modern"])
def test_optional_authorized_vendor_contract_starts_full_server(mode):
    source = os.environ.get("AUDATIS_TEST_VENDOR_SPEC_PATH")
    if not source:
        pytest.skip("Supply AUDATIS_TEST_VENDOR_SPEC_PATH privately for full contract integration")
    result = child(LIST_TOOLS, AUDATIS_OPENAPI_SPEC_PATH=str(Path(source).resolve()),
                   AUDATIS_MCP_TOOL_NAMES=mode)
    assert result["catalog"]["status"] == "available"
    assert result["catalog"]["operation_count"] == 177
    golden = json.loads((ROOT / "tests/fixtures/tools_226.json").read_text())[mode]
    assert set(result["names"]) == set(golden) | {"module_capabilities"}
    assert len(result["names"]) == 227


@pytest.mark.parametrize("damage", ["version", "dialect", "paths", "schemas", "external_ref",
                                     "unresolved_ref", "path", "operation", "responses", "risk_write"])
def test_invalid_structure_disables_optional_catalog_not_server(tmp_path, damage):
    spec = copy.deepcopy(synthetic_spec())
    risks = spec["paths"]["/api/v1/clients/{mid}/risks"]
    if damage == "version":
        spec["info"]["version"] = "9.9.9"
    elif damage == "dialect":
        spec["openapi"] = "3.1.0"
    elif damage == "paths":
        spec["paths"] = []
    elif damage == "schemas":
        spec["components"]["schemas"] = []
    elif damage in ("external_ref", "unresolved_ref"):
        spec["components"]["schemas"]["Example"] = {
            "$ref": "https://untrusted.invalid/schema" if damage == "external_ref" else "#/components/schemas/Absent"}
    elif damage == "path":
        spec["paths"]["https://untrusted.invalid/path"] = risks
    elif damage == "operation":
        risks["get"]["operationId"] = "invalid-name"
    elif damage == "responses":
        risks["get"]["responses"] = {}
    else:
        risks["post"] = risks.pop("get")
    path = tmp_path / "invalid.json"
    sha = write_spec(path, spec)
    result = child(LIST_TOOLS, AUDATIS_OPENAPI_SPEC_PATH=str(path), AUDATIS_OPENAPI_SPEC_SHA256=sha)
    assert len(result["names"]) == 48
    assert result["catalog"]["status"] == "invalid"


def test_invalid_request_schema_disables_catalog_without_partial_registration(tmp_path):
    spec = synthetic_spec()
    spec["paths"]["/api/v1/clients/{mid}/measures"]["post"]["requestBody"] = "not an object"
    path = tmp_path / "invalid-body.json"
    sha = write_spec(path, spec)
    result = child(LIST_TOOLS, AUDATIS_OPENAPI_SPEC_PATH=str(path), AUDATIS_OPENAPI_SPEC_SHA256=sha)
    assert len(result["names"]) == 48 and result["catalog"]["status"] == "invalid"


@pytest.mark.parametrize("raw", [b'{"paths":{},"paths":{}}', b'{"x":NaN}', b'not json'])
def test_json_corruption_is_sanitized(tmp_path, raw):
    path = tmp_path / "PRIVATE_CANARY.json"
    path.write_bytes(raw)
    result = child(LIST_TOOLS, AUDATIS_OPENAPI_SPEC_PATH=str(path),
                   AUDATIS_OPENAPI_SPEC_SHA256=hashlib.sha256(raw).hexdigest())
    assert len(result["names"]) == 48
    assert result["catalog"]["status"] == "invalid"
    assert "PRIVATE_CANARY" not in json.dumps(result)


def test_default_hash_pin_is_not_relaxed_for_synthetic_contract(local_catalog):
    result = child(LIST_TOOLS, AUDATIS_OPENAPI_SPEC_PATH=str(local_catalog))
    assert len(result["names"]) == 48 and result["catalog"]["status"] == "invalid"


def test_local_loader_rejects_symlinks(tmp_path):
    target = tmp_path / "source.json"
    sha = write_spec(target, synthetic_spec())
    link = tmp_path / "link.json"
    link.symlink_to(target)
    with pytest.raises(RuntimeError):
        catalog.load_spec(link, sha)


def test_catalog_selection_is_immutable_until_restart(local_catalog, monkeypatch):
    assert len(catalog.OPERATIONS) == 2
    with monkeypatch.context() as patch:
        patch.setenv("AUDATIS_OPENAPI_SPEC_PATH", "")
        assert len(catalog.OPERATIONS) == 2


def test_synthetic_operations_keep_preview_validation_and_mock_transport(local_catalog, monkeypatch):
    from management_core import ManagementAPI, run_operation
    monkeypatch.setattr(ManagementAPI, "from_env", classmethod(
        lambda cls: pytest.fail("Preview must not access credentials")))
    preview = run_operation("create_measure", payload_json='{"title":"Synthetic check"}')
    assert preview["will_write"] is False and preview["mode"] == "preview"
    with pytest.raises(ValueError):
        run_operation("create_measure", payload_json='{"title":"x","extra":"not allowed"}')
    calls = []
    def respond(request):
        calls.append(request)
        assert request.url.host == "tenant.example.test"
        assert request.method == "POST"
        return httpx.Response(201, json={"data": {"id": 1}})
    api = ManagementAPI("https://tenant.example.test", "FAKE_READ",
                        write_token="FAKE_WRITE", transport=httpx.MockTransport(respond))
    monkeypatch.setattr(ManagementAPI, "from_env", classmethod(lambda cls: api))
    result = run_operation("create_measure", payload_json='{"title":"Synthetic check"}', execute=True)
    assert result["ok"] and len(calls) == 1


def test_real_stdio_base_server_starts_without_specification():
    from mcp import ClientSession, StdioServerParameters
    from mcp.client.stdio import stdio_client
    code = (
        "import dotenv,runpy,socket\n"
        "dotenv.load_dotenv=lambda *a,**k:False\n"
        "def blocked(*a,**k):raise RuntimeError('No network')\n"
        "socket.socket.connect=blocked\nsocket.socket.connect_ex=blocked\n"
        "runpy.run_module('server',run_name='__main__')\n"
    )
    params = StdioServerParameters(command=sys.executable, args=["-c", code], cwd=str(ROOT),
                                  env={"AUDATIS_OPENAPI_SPEC_PATH": "", "AUDATIS_MCP_MODULES": "all",
                                       "AUDATIS_CLIENT_ID": "0", "AUDATIS_ALLOWED_CLIENT_ID": "12345"})
    async def run():
        async with stdio_client(params) as (read, write):
            async with ClientSession(read, write) as session:
                await session.initialize()
                tools = await session.list_tools()
                assert len(tools.tools) == 48
    asyncio.run(asyncio.wait_for(run(), timeout=30))
