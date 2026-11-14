"""Read-only bridge to EXISTING MCP tools, respecting their module guards."""
from __future__ import annotations

import importlib
import inspect
import json
from datetime import datetime, timezone
from pathlib import Path

from .model import RESOURCES, empty_bundle, source, validate_bundle

READ_TOOLS = frozenset({"list_records", "get_record", "lookup_values"})
FIELDS = {
    "assets": {"id", "title", "description", "category_id", "type_id", "asset_owner_user_id",
               "protection_needs", "information_values", "measures", "linked_assets", "parent_id", "is_group"},
    "information-values": {"id", "title", "description", "asset_owner_user_id", "protection_needs",
                           "linked_assets", "next_review_at"},
    "business-processes": {"id", "title", "description", "process_owner_id", "process", "asset_ids",
                           "information_value_ids", "measure_ids", "risk_ids", "parent_id", "next_review_at"},
    "measures": {"id", "title", "description", "responsible_user_id", "implementation_status", "monitoring",
                 "asset_ids", "business_process_ids", "risk_ids", "next_review_at"},
    "risks": {"id", "designation", "description", "owner_user_id", "responsible_user_id", "status_code",
              "gross_risk", "net_risk", "target_risk"},
    "tasks": {"id", "subject", "description", "assigned_to_user_id", "status", "due_date"},
}


class ReadSourceError(RuntimeError):
    pass


class ExistingMCPReader:
    """No arbitrary tool names or REST URLs; never calls create/update/delete tools."""

    def __init__(self, mcp, names: dict, expected_client_id: int):
        self._mcp, self._names = mcp, names
        self.expected_client_id = expected_client_id

    @classmethod
    async def local(cls):
        from mcp_naming import TOOL_NAME_MAP
        from task_direct import EXPECTED_CLIENT_ID
        base = importlib.import_module("server")
        if Path(base.__file__).resolve() != Path(__file__).resolve().parents[1] / "server.py":
            raise ReadSourceError("Nicht der erwartete lokale audatisControl-Server")
        tools = base.mcp.list_tools()
        if inspect.isawaitable(tools):
            tools = await tools
        names = {TOOL_NAME_MAP.get(t.name, t.name): t.name for t in tools}
        return cls(base.mcp, names, EXPECTED_CLIENT_ID)

    async def call(self, name: str, arguments: dict) -> dict:
        if name not in READ_TOOLS or name not in self._names:
            raise ReadSourceError("Lesetool nicht erlaubt oder im Modulprofil nicht verfügbar")
        result = self._mcp.call_tool(self._names[name], arguments)
        if inspect.isawaitable(result):
            result = await result
        if getattr(result, "is_error", False):
            raise ReadSourceError("MCP-Leseaufruf nicht erfolgreich")
        structured = getattr(result, "structured_content", None)
        if isinstance(structured, dict):
            body = structured.get("result", structured)
        else:
            try:
                body = json.loads(result.content[0].text)
            except (AttributeError, IndexError, TypeError, ValueError):
                raise ReadSourceError("MCP-Leseantwort nicht auswertbar") from None
        if not isinstance(body, dict) or body.get("ok") is False:
            raise ReadSourceError("Lesetool nicht erfolgreich; Rechte/Modulprofil prüfen")
        if type(body.get("client_id")) is not int or body["client_id"] != self.expected_client_id:
            raise ReadSourceError("Mandantenprüfung der Leseantwort fehlgeschlagen")
        return body


def validate_options(resources, max_pages, max_records):
    if not isinstance(resources, list) or not resources or any(not isinstance(r, str) or r not in RESOURCES for r in resources):
        raise ValueError("Mindestens eine freigegebene Fachressource angeben")
    if len(resources) != len(set(resources)):
        raise ValueError("Ressourcen nicht doppelt angeben")
    if type(max_pages) is not int or not 1 <= max_pages <= 10:
        raise ValueError("max_pages muss 1..10 sein")
    if type(max_records) is not int or not 1 <= max_records <= 1000:
        raise ValueError("max_records muss 1..1000 sein")


async def collect(reader, organisation: str, as_of: str, captured_at: str, resources: list[str],
                  *, scope: dict | None = None, max_pages: int = 5, max_records: int = 200) -> dict:
    validate_options(resources, max_pages, max_records)
    client = "audatis:" + str(reader.expected_client_id)
    bundle = empty_bundle(organisation, as_of, captured_at, client, synthetic=False, scope=scope)
    validate_bundle(bundle)  # Validate dates/scope before the first authorized read.
    calls, records = 0, 0
    max_calls = min(1200, max_records + len(resources) * max_pages + 1)
    explicit = bundle["context"]["scope"]["object_ids"]
    selected_resources = [r for r in resources if explicit is None or explicit.get(r)]

    async def read(tool, arguments, resource=None, *, is_record=False):
        nonlocal calls
        if tool not in READ_TOOLS or calls >= max_calls:
            raise ReadSourceError("Lokales Aufruflimit erreicht")
        calls += 1
        try:
            result = await reader.call(tool, arguments)
            if (result.get("ok") is False or type(result.get("client_id")) is not int
                    or result["client_id"] != reader.expected_client_id):
                raise ReadSourceError("Mandant/Modul oder Quelle nicht überprüfbar")
            data = result["data"]
            if is_record:
                if not isinstance(data, dict) or data.get("id") != arguments["record_id"]:
                    raise ReadSourceError("Objekt-ID oder Datenformat abweichend")
                # Preserve omitted fields as OMITTED, not as fabricated nulls.
                data = {k: v for k, v in data.items() if k in FIELDS[resource]}
            elif tool == "list_records":
                if not isinstance(data, list) or any(not isinstance(row, dict) or not isinstance(row.get("id"), str) for row in data):
                    raise ReadSourceError("Listenformat nicht auswertbar")
                data = {"ids": [row["id"] for row in data], "meta": result.get("meta")}
            else:
                if not isinstance(data, list):
                    raise ReadSourceError("Schutzbedarfsstufen nicht auswertbar")
                data = {"levels": [{k: row[k] for k in ("level", "name", "is_active") if k in row}
                                   for row in data if isinstance(row, dict)]}
            entry = source(tool, arguments, client, data)
        except Exception:
            entry = source(tool, arguments, client, None, state="unavailable",
                           reason="Lesequelle nicht überprüfbar; keine Fehler-/Payloadinhalte übernommen")
        bundle["sources"].append(entry)
        return entry

    if "assets" in selected_resources:
        ref = await read("lookup_values", {"name": "asset_protection_levels"})
        bundle["references"]["asset_protection_levels"] = ref["source_id"]
    for resource in RESOURCES:
        if resource not in selected_resources:
            continue
        info = bundle["resources"][resource]
        info.update(state="partial", reason="Erhebung begonnen")
        seen, expected_total, expected_pages, detail_failed = set(), None, None, False
        if records >= max_records:
            info.update(state="unavailable", reason="Lokales Datensatzlimit erreicht; nicht erhoben")
            continue
        if explicit is not None:
            info["reason"] = "Explizite Objektauswahl; kein vollständiger Inventarabruf und keine automatische Abhängigkeitsexpansion"
            for obj_id in sorted(explicit[resource]):
                if records >= max_records:
                    info["reason"] = "Lokales Datensatzlimit; Primärauswahl unvollständig"
                    break
                entry = await read("get_record", {"resource": resource, "record_id": obj_id}, resource, is_record=True)
                records += 1
                info["source_ids"].append(entry["source_id"])
                if entry["state"] == "ok":
                    info["records"].append(entry["source_id"])
            if not info["records"]:
                info.update(state="unavailable", reason="Beauftragte Objekte nicht abrufbar")
            continue
        for page in range(1, max_pages + 1):
            page_source = await read("list_records", {"resource": resource, "page": page, "per_page": 100})
            info["source_ids"].append(page_source["source_id"])
            if page_source["state"] != "ok":
                info.update(state="partial" if info["records"] else "unavailable", reason="Liste nicht abrufbar")
                break
            page_data = page_source["data"]
            ids, meta = page_data["ids"], page_data["meta"]
            if (not isinstance(meta, dict) or type(meta.get("total_pages")) is not int
                    or type(meta.get("total")) is not int or meta["total_pages"] < 0 or meta["total"] < 0
                    or (meta.get("page") is not None and meta["page"] != page)
                    or (expected_total is not None and expected_total != meta["total"])
                    or (expected_pages is not None and expected_pages != meta["total_pages"])
                    or (meta["total_pages"] == 0 and (meta["total"] != 0 or ids))):
                info["reason"] = "Pagination oder Bestandskonsistenz nicht belegt"
                break
            expected_total = meta["total"]
            expected_pages = meta["total_pages"]
            duplicate = bool(seen.intersection(ids)) or len(ids) != len(set(ids))
            if duplicate:
                info["reason"] = "Wiederholte Objekt-IDs zwischen/innerhalb Seiten"
                break
            seen.update(ids)
            for obj_id in ids:
                if records >= max_records:
                    detail_failed = True
                    break
                record = await read("get_record", {"resource": resource, "record_id": obj_id}, resource, is_record=True)
                info["source_ids"].append(record["source_id"])
                records += 1
                if record["state"] == "ok":
                    info["records"].append(record["source_id"])
                else:
                    detail_failed = True
            if records >= max_records and (page < meta["total_pages"] or len(info["records"]) < len(seen)):
                info["reason"] = "Lokales Datensatzlimit; keine Vollständigkeitsbehauptung"
                break
            if page >= meta["total_pages"]:
                if len(seen) == expected_total and not detail_failed:
                    info.update(state="complete", reason="Alle gemeldeten Seiten und Datensatzdetails erhoben; API-Sichtbestand")
                else:
                    info["reason"] = "Datensatzdetails oder Seitenanzahl unvollständig"
                break
            info["reason"] = "Seitenlimit erreicht; Erhebung unvollständig"
    validate_bundle(bundle)
    return bundle


async def collect_authorized(organisation: str, as_of: str, resources: list[str], *,
                             scope: dict | None = None, max_pages: int = 5, max_records: int = 200,
                             allow_live_read: bool = False, acknowledge_sensitive_output: bool = False):
    validate_options(resources, max_pages, max_records)
    if type(allow_live_read) is not bool or type(acknowledge_sensitive_output) is not bool:
        raise ValueError("Freigaben müssen Boolean sein")
    captured_at = datetime.now(timezone.utc).isoformat(timespec="seconds")
    check = empty_bundle(organisation, as_of, captured_at, "preview", synthetic=False, scope=scope)
    validate_bundle(check)
    if not allow_live_read or not acknowledge_sensitive_output:
        return {"mode": "preview", "will_write": False, "will_read": False,
                "required_consents": ["allow_live_read=true", "acknowledge_sensitive_output=true"],
                "read_tools": sorted(READ_TOOLS), "resources": resources, "max_pages": max_pages,
                "max_records": max_records,
                "scope_mode": "explicit_objects" if check["context"]["scope"]["object_ids"] is not None else "visible_inventory",
                "automatic_dependency_expansion": False,
                "warning": "Reale Daten würden im MCP-Ergebnis an den konfigurierten Client zurückgegeben. "
                           "Verarbeitungsort/Empfänger vor Freigabe prüfen; kein externer KI-Aufruf durch den Copilot."}
    reader = await ExistingMCPReader.local()
    return await collect(reader, organisation, as_of, captured_at, resources, scope=scope,
                         max_pages=max_pages, max_records=max_records)
