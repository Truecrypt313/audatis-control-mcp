"""Asset demo through real MCP SDK registrations with synthetic HTTP transport only."""
from __future__ import annotations

import asyncio
import importlib
import json
import sys
from datetime import datetime
from pathlib import Path
from uuid import UUID
from zoneinfo import ZoneInfo

import httpx
import pytest

from isms_copilot.__main__ import artifacts, main
from isms_copilot.asset_demo import DEMO_ASSETS, asset_demo_bundle, creation_plan
from isms_copilot.assessment import assess
from isms_copilot.model import digest, seal, source, verify_seal
from isms_copilot.planner import plan_remediation, validate_plan
from isms_copilot.report import render_report
from isms_copilot.tools import TOOLS, register_copilot_tools

ROOT = Path(__file__).resolve().parents[1]
uid = lambda n: str(UUID(int=n))


def unpack(result):
    assert not result.is_error
    structured = getattr(result, "structured_content", None)
    return structured.get("result", structured) if isinstance(structured, dict) else json.loads(result.content[0].text)


class Backend:
    """Own fixture labels and IDs, not a vendor specification or customer export."""
    def __init__(self, fail_at=None, missing_id_at=None):
        self.fail_at, self.missing_id_at = fail_at, missing_id_at
        self.posts, self.calls, self.rows = 0, [], []
        self.categories = [
            {"id": uid(501), "name": "Netzwerk & Infrastruktur", "is_active": True},
            {"id": uid(502), "name": "Systeme", "is_active": True},
        ]
        self.types = {
            uid(501): [{"id": uid(601), "name": "Firewall", "category_id": uid(501), "is_active": True}],
            uid(502): [{"id": uid(602), "name": "Server", "category_id": uid(502), "is_active": True},
                       {"id": uid(603), "name": "Client / Arbeitsplatz", "category_id": uid(502), "is_active": True}],
        }

    def __call__(self, request):
        self.calls.append((request.method, request.url.path))
        assert request.url.host == "tenant.example.test"
        assert request.url.path.startswith("/api/v1/clients/12345/")
        path = request.url.path.removeprefix("/api/v1/clients/12345/")
        if path == "assets/categories":
            return httpx.Response(200, json={"data": self.categories})
        if path.startswith("assets/categories/") and path.endswith("/types"):
            return httpx.Response(200, json={"data": self.types[path.split("/")[2]]})
        if path == "assets/statuses":
            return httpx.Response(200, json={"data": [{"id": uid(401), "name": "Aktiv", "is_archive": False}]})
        if path == "assets/protection-levels":
            return httpx.Response(200, json={"data": [{"level": 1, "name": "Normal"}]})
        if path == "assets" and request.method == "POST":
            index = self.posts
            self.posts += 1
            if index == self.fail_at:
                return httpx.Response(500, json={"error": "synthetic uncertainty"})
            row = {"id": uid(700 + index), **json.loads(request.content), "asset_owner_user_id": None,
                   "description": None, "is_archived": False, "status_id": uid(401),
                   "protection_needs": {d: None for d in ("confidentiality", "integrity", "availability")},
                   "information_values": [], "measures": [], "linked_assets": [], "parent_id": None}
            self.rows.append(row)
            if index == self.missing_id_at:
                return httpx.Response(201, json={"data": {"title": row["title"]}})
            return httpx.Response(201, json={"data": row})
        if path == "assets":
            page = int(request.url.params.get("page", 1))
            pages = max(1, (len(self.rows) + 1) // 2)
            return httpx.Response(200, json={"data": self.rows[(page - 1) * 2:page * 2],
                                           "meta": {"total": len(self.rows), "page": page, "total_pages": pages}})
        row = next((r for r in self.rows if path == "assets/" + r["id"]), None)
        assert row is not None, path
        return httpx.Response(200, json={"data": row})


def setup_mcp(monkeypatch, backend):
    from mcp.server import MCPServer
    import asset_management
    import v2_core
    monkeypatch.setenv("AUDATIS_MCP_MODULES", "core,assets")
    monkeypatch.setenv("AUDATIS_MCP_TOOL_NAMES", "modern")
    monkeypatch.setenv("AUDATIS_BASE_URL", "https://tenant.example.test")
    monkeypatch.setenv("AUDATIS_CLIENT_ID", "12345")
    monkeypatch.setenv("AUDATIS_ALLOWED_CLIENT_ID", "12345")
    monkeypatch.setenv("AUDATIS_API_TOKEN", "FAKE_READ")
    monkeypatch.setattr(asset_management, "_write_token", lambda: "FAKE_WRITE")
    monkeypatch.setattr(v2_core, "_write_token", lambda: "FAKE_WRITE")
    original = httpx.Client
    def client(*args, **kwargs):
        kwargs["transport"] = httpx.MockTransport(backend)
        return original(*args, **kwargs)
    monkeypatch.setattr(httpx, "Client", client)
    monkeypatch.delitem(sys.modules, "server", raising=False)
    base = importlib.import_module("server")
    copilot = MCPServer("offline-asset-demo")
    register_copilot_tools(copilot)
    return base.mcp, copilot


async def prepare(base, backend):
    # All pages, then actual category/type lookup responses. No hardcoded IDs.
    existing, page = [], 1
    while True:
        response = unpack(await base.call_tool("list_assets", {"page": page, "per_page": 100}))
        existing.extend(response["data"])
        if page >= response["meta"]["total_pages"]:
            break
        page += 1
    categories = unpack(await base.call_tool("list_asset_categories", {}))["data"]
    types = {}
    for category in categories:
        types[category["id"]] = unpack(await base.call_tool("list_asset_types", {"category_id": category["id"]}))["data"]
    items = creation_plan(categories, types, existing, inventory_complete=True)
    before = len(backend.calls)
    preview = unpack(await base.call_tool("bulk_create_records",
                                        {"resource": "assets", "items_json": json.dumps(items), "execute": False}))
    assert preview["execute"] is False and len(backend.calls) == before
    assert backend.posts == 0
    return items


@pytest.mark.parametrize("fail_at", [None, 0, 1, 2])
def test_three_intents_with_explicit_confirmation_and_partial_successes(monkeypatch, fail_at):
    backend = Backend(fail_at)
    base, copilot = setup_mcp(monkeypatch, backend)
    async def run():
        names = {t.name for t in await base.list_tools()}
        assert {"list_assets", "get_asset", "list_asset_categories", "list_asset_types",
                "bulk_create_records", "get_record", "lookup_values"} <= names
        assert len(await copilot.list_tools()) == 7
        items = await prepare(base, backend)
        assert [item["title"] for item in items] == [a[0] for a in DEMO_ASSETS]
        assert [item["type_id"] for item in items] == [uid(601), uid(602), uid(603)]
        # The client pauses here. Only a subsequent explicit confirmation selects execute=True.
        assert backend.posts == 0
        outcome = unpack(await base.call_tool("bulk_create_records",
                         {"resource": "assets", "items_json": json.dumps(items),
                          "execute": True, "check_existing": True}))
        created = outcome["created"]
        assert len(created) == (3 if fail_at is None else fail_at)
        assert backend.posts == (3 if fail_at is None else fail_at + 1)
        assert outcome["completed"] is (fail_at is None)
        assert not any(method == "DELETE" for method, _ in backend.calls)
        if not created:
            return  # Never fall back to assessing all assets after an unsuccessful creation.
        scope = {"name": "Bestätigte Demo-Erstellungen", "object_ids": {"assets": [r["id"] for r in created]}}
        as_of = datetime.now(ZoneInfo("Europe/Berlin")).date().isoformat()
        result = unpack(await copilot.call_tool("collect_assessment",
                        {"organisation": "Synthetischer MCP-Test", "as_of": as_of,
                         "resources_json": '["assets"]', "scope_json": json.dumps(scope),
                         "allow_live_read": True, "acknowledge_sensitive_output": True}))
        assessment = result["assessment"]
        assert {obj["object_id"] for obj in assessment["inventory"]} == {r["id"] for r in created}
        assert all(obj["asset_details"]["status_label"] == "Aktiv" for obj in assessment["inventory"])
        plan = unpack(await copilot.call_tool("plan_remediation", {"assessment_json": json.dumps(assessment)}))
        assert len(plan["actions"]) <= 3
        validate_plan(plan, assessment)
        report = unpack(await copilot.call_tool("render_consulting_report",
                        {"assessment_json": json.dumps(assessment), "plan_json": json.dumps(plan)}))
        assert "Asset Assessment – Management Summary" in report["html"]
        assert report["html"].count('class="recommendation"') <= 3
        assert report["html"].count('class="finding"') <= 3
        assert len(report["technical_details"]["assessment"]["findings"]) == len(assessment["findings"])
        assert backend.posts == (3 if fail_at is None else fail_at + 1)  # Analysis never retries writes.
        disabled = unpack(await base.call_tool("get_record", {"resource": "tasks", "record_id": uid(999)}))
        assert disabled["error_type"] == "module_disabled"
    try:
        asyncio.run(run())
    finally:
        monkeypatch.delitem(sys.modules, "server", raising=False)


def test_race_duplicate_is_stopped_by_existing_bulk_preflight(monkeypatch):
    backend = Backend()
    base, _ = setup_mcp(monkeypatch, backend)
    async def run():
        items = await prepare(base, backend)
        backend.rows.append({"id": uid(999), "title": "  demo-fw-01  "})
        result = unpack(await base.call_tool("bulk_create_records",
                        {"resource": "assets", "items_json": json.dumps(items), "execute": True}))
        assert result["ok"] is False
        assert backend.posts == 0
    try:
        asyncio.run(run())
    finally:
        monkeypatch.delitem(sys.modules, "server", raising=False)


def test_uncertain_creation_without_returned_id_is_not_retried_or_assessed(monkeypatch):
    backend = Backend(missing_id_at=1)
    base, copilot = setup_mcp(monkeypatch, backend)
    async def run():
        items = await prepare(base, backend)
        outcome = unpack(await base.call_tool("bulk_create_records",
                         {"resource": "assets", "items_json": json.dumps(items), "execute": True}))
        assert outcome["completed"] is False and len(outcome["created"]) == 1
        assert backend.posts == 2 and len(backend.rows) == 2
        confirmed = [row["id"] for row in outcome["created"]]
        scope = {"name": "Nur bestätigte Erstellungen", "object_ids": {"assets": confirmed}}
        result = unpack(await copilot.call_tool("collect_assessment",
                        {"organisation": "Synthetischer Unsicherheitsfall",
                         "as_of": datetime.now(ZoneInfo("Europe/Berlin")).date().isoformat(),
                         "resources_json": '["assets"]', "scope_json": json.dumps(scope),
                         "allow_live_read": True, "acknowledge_sensitive_output": True}))
        assert [row["object_id"] for row in result["assessment"]["inventory"]] == confirmed
        unknown = backend.rows[1]["id"]
        assert not any(method == "GET" and path.endswith("/" + unknown) for method, path in backend.calls)
        assert backend.posts == 2
    try:
        asyncio.run(run())
    finally:
        monkeypatch.delitem(sys.modules, "server", raising=False)


@pytest.mark.parametrize("damage", ["incomplete", "duplicate", "category", "type", "ambiguous", "missing_name"])
def test_plan_requires_complete_inventory_and_actual_unambiguous_lookups(damage):
    backend = Backend()
    existing = [{"title": "demo-fw-01"}] if damage == "duplicate" else []
    if damage == "missing_name":
        existing = [{"id": uid(999)}]
    if damage == "category":
        backend.categories.pop()
    if damage == "type":
        backend.types[uid(502)].pop()
    if damage == "ambiguous":
        backend.categories.append(dict(backend.categories[0]))
    with pytest.raises(ValueError):
        creation_plan(backend.categories, backend.types, existing, inventory_complete=damage != "incomplete")


def test_collection_budget_includes_both_lookups_at_exact_page_and_record_limits(monkeypatch):
    backend = Backend()
    bundle = asset_demo_bundle()
    backend.rows = [s["data"] for s in bundle["sources"]
                    if s["source_id"] in bundle["resources"]["assets"]["records"]]
    setup_mcp(monkeypatch, backend)
    from isms_copilot.collector import ExistingMCPReader, collect
    async def run():
        reader = await ExistingMCPReader.local()
        result = await collect(reader, "Synthetischer Grenzfall", "2026-11-14",
                               "2026-11-14T10:00:00+01:00", ["assets"], max_pages=2, max_records=3)
        assert result["resources"]["assets"]["state"] == "complete"
        assert len(result["resources"]["assets"]["records"]) == 3
        assert set(result["references"]) == {"asset_statuses", "asset_protection_levels"}
    try:
        asyncio.run(run())
    finally:
        monkeypatch.delitem(sys.modules, "server", raising=False)


def edit_asset(bundle, **changes):
    row = next(s for s in bundle["sources"] if s["source_id"] in bundle["resources"]["assets"]["records"])
    row["data"].update(changes)
    row["data_sha256"] = digest(row["data"])
    return row


@pytest.mark.parametrize("status_id,archived,expected", [
    (uid(401), False, None), (None, False, "missing_documentation"),
    (uid(999), False, "not_verifiable"), (uid(401), "false", "not_verifiable"),
    (uid(401), True, "not_verifiable"),
])
def test_status_and_archive_are_documented_states_not_health(status_id, archived, expected):
    bundle = asset_demo_bundle()
    edit_asset(bundle, status_id=status_id, is_archived=archived)
    assessment = assess(bundle)
    findings = [f for f in assessment["findings"] if f["rule_id"].startswith("asset_")]
    assert (expected in {f["status"] for f in findings}) if expected else not findings
    html = render_report(assessment)["html"]
    assert "Inventarstatus ist kein Nachweis technischer Funktionsfähigkeit" in html


def test_omitted_archive_and_status_are_not_fabricated_as_null_or_false():
    bundle = asset_demo_bundle()
    row = edit_asset(bundle)
    del row["data"]["status_id"]
    del row["data"]["is_archived"]
    row["data_sha256"] = digest(row["data"])
    assessment = assess(bundle)
    fs = [f for f in assessment["findings"] if f["rule_id"].startswith("asset_")]
    assert all(f["status"] == "not_verifiable" for f in fs)
    assert all(not f["evidence"][0]["present"] for f in fs)


def test_consistent_archived_state_is_not_treated_as_an_outage():
    bundle = asset_demo_bundle()
    entry = next(s for s in bundle["sources"] if s["source_id"] == bundle["references"]["asset_statuses"])
    entry["data"]["statuses"].append({"id": uid(402), "name": "Archiviert", "is_archive": True})
    entry["data_sha256"] = digest(entry["data"])
    edit_asset(bundle, status_id=uid(402), is_archived=True)
    assessment = assess(bundle)
    assert not any(f["rule_id"].startswith("asset_") for f in assessment["findings"])
    assert "Archiviert" in render_report(assessment)["html"]


def test_asset_plan_covers_every_finding_exactly_once_in_at_most_three_actions():
    assessment = assess(asset_demo_bundle())
    plan = plan_remediation(assessment)
    assert 0 < len(plan["actions"]) <= 3
    validate_plan(plan, assessment)
    referenced = [fid for a in plan["actions"] for fid in a["finding_ids"]]
    assert len(set(referenced)) == len(referenced) == len(assessment["findings"])
    assert all(action["will_write"] is False and action["status"] == "proposal" for action in plan["actions"])
    report = render_report(assessment, plan)
    assert report == render_report(assessment, plan)
    for row in assessment["inventory"]:
        assert row["object_id"] not in report["html"]  # Technical IDs stay in structured details.
    assert set(artifacts(asset_demo_bundle())) == {"report.md", "report.html", "details.json"}
    verify_seal(json.loads(artifacts(asset_demo_bundle())["details.json"]), "details_sha256")


def test_short_report_escapes_untrusted_data_and_caps_large_overviews():
    bundle = asset_demo_bundle()
    bundle["context"]["organisation"] = '<script>alert(1)</script>' + "long " * 20
    row = edit_asset(bundle, title='<img src="https://untrusted.invalid/a">' + "long" * 100)
    info = bundle["resources"]["assets"]
    for i in range(10):
        data = {**row["data"], "id": uid(1000 + i)}
        entry = source("get_record", {"resource": "assets", "record_id": data["id"]},
                       bundle["context"]["client_reference"], data)
        bundle["sources"].append(entry)
        info["records"].append(entry["source_id"])
        info["source_ids"].append(entry["source_id"])
        bundle["context"]["scope"]["object_ids"]["assets"].append(data["id"])
    result = render_report(assess(bundle))
    assert "<script>" not in result["html"] and "<img" not in result["html"]
    assert "&lt;script&gt;" in result["html"]
    assert "6 von 13" in result["html"]
    assert len(result["technical_details"]["displayed_asset_ids"]) == 6
    assert len(result["technical_details"]["assessment"]["inventory"]) == 13


def test_preexisting_asset_assessment_contract_still_renders_without_new_optional_fields():
    assessment = assess(asset_demo_bundle())
    assessment["ruleset_version"] = "consulting-docs-1.0"
    for obj in assessment["inventory"]:
        obj.pop("asset_details")
    assessment = seal({k: v for k, v in assessment.items() if k != "assessment_sha256"}, "assessment_sha256")
    plan = plan_remediation(assessment)
    validate_plan(plan, assessment)
    assert render_report(assessment, plan)["format"] == "asset-management-summary"


@pytest.mark.parametrize("output", ["../outside", "absolute"])
def test_cli_cannot_export_outside_operator_defined_root(tmp_path, monkeypatch, output):
    root = tmp_path / "exports"
    monkeypatch.setenv("AUDATIS_COPILOT_OUTPUT_DIR", str(root))
    destination = str(tmp_path / "outside") if output == "absolute" else output
    with pytest.raises(SystemExit):
        main(["demo", "--output", destination])
    assert not (tmp_path / "outside").exists()
    assert not root.exists()


def test_cli_exports_only_three_private_files_and_respects_checks(tmp_path, monkeypatch):
    root = tmp_path / "exports"
    monkeypatch.setenv("AUDATIS_COPILOT_OUTPUT_DIR", str(root))
    assert main(["demo"]) == 0
    assert {p.name for p in root.iterdir()} == {"report.html", "report.md", "details.json"}
    assert main(["demo", "--check"]) == 0
    assert root.stat().st_mode & 0o077 == 0
    assert all(p.stat().st_mode & 0o077 == 0 for p in root.iterdir())
    data = json.loads((root / "details.json").read_text())
    verify_seal(data, "details_sha256")
    assert len(data["bundle"]["resources"]["assets"]["records"]) == 3
    assert len(data["plan"]["actions"]) <= 3


def test_cli_rejects_symlink_output_and_nonprivate_root(tmp_path, monkeypatch):
    root = tmp_path / "exports"
    root.mkdir(mode=0o700)
    monkeypatch.setenv("AUDATIS_COPILOT_OUTPUT_DIR", str(root))
    (root / "linked").symlink_to(tmp_path, target_is_directory=True)
    with pytest.raises(SystemExit):
        main(["demo", "--output", "linked"])
    root.chmod(0o755)
    with pytest.raises(SystemExit):
        main(["demo"])


def test_atomic_export_cannot_truncate_a_hardlinked_file_outside_root(tmp_path, monkeypatch):
    root = tmp_path / "exports"
    root.mkdir(mode=0o700)
    outside = tmp_path / "outside.md"
    outside.write_text("USER WORK")
    (root / "report.md").hardlink_to(outside)
    monkeypatch.setenv("AUDATIS_COPILOT_OUTPUT_DIR", str(root))
    assert main(["demo", "--overwrite"]) == 0
    assert outside.read_text() == "USER WORK"
    assert (root / "report.md").read_text() != "USER WORK"
