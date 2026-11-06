"""MCP-facing V2 catalog, reference data, CRUD, risk detail and incident links.

No DELETE or incident creation/status transition is exposed.
"""
from __future__ import annotations

from v2_core import (V2API, ALLOWED_FIELDS, LOOKUPS, LINK_KINDS, READ_RESOURCES,
                     WRITE_RESOURCES, parse_json, uuid_id, validate_payload)
from task_direct import EXPECTED_CLIENT_ID

# Minimal fields: avoid returning unneeded private data in list and tools results.
SUMMARY = {
    "assets": ("id", "title", "category_id", "type_id", "parent_id", "asset_owner_user_id", "is_group", "is_archived", "protection_needs", "linked_assets", "information_values", "measures", "risks"),
    "tasks": ("id", "number", "subject", "status", "priority", "due_date", "assigned_to_user_id"),
    "information-values": ("id", "title", "asset_owner_user_id", "classification_id", "has_personal_reference", "protection_needs", "linked_assets", "is_archived", "next_review_at"),
    "business-processes": ("id", "title", "process_owner_id", "parent_id", "status", "criticality", "asset_ids", "information_value_ids", "measure_ids", "risk_ids", "next_review_at"),
    "measures": ("id", "measure_nr", "title", "type", "implementation_status", "responsible_user_id", "asset_ids", "risk_ids", "business_process_ids", "next_review_at"),
    "risks": ("id", "risk_nr", "designation", "status_code", "risk_type_code", "gross_risk", "net_risk", "owner_user_id", "responsible_user_id"),
    "incidents": ("id", "incident_number", "title", "status_code", "severity", "classification_code", "became_known_at", "is_archived"),
    "reports": ("id", "designation", "report_status", "updated_at"),
}


def _project(resource: str, record: dict) -> dict:
    if not isinstance(record, dict):
        raise RuntimeError("API-Eintrag ist kein Objekt")
    return {k: record.get(k) for k in SUMMARY[resource]}


def v2_capabilities() -> dict:
    """Zeigt die geprüften V2-Ressourcen, Felder und API-Grenzen (keine Änderungen)."""
    return {
        "client_id": EXPECTED_CLIENT_ID,
        "read_resources": sorted(READ_RESOURCES),
        "create_update_resources": sorted(WRITE_RESOURCES),
        "write_fields": {r: {m: sorted(v) for m, v in ops.items()} for r, ops in ALLOWED_FIELDS.items()},
        "lookups": sorted(LOOKUPS),
        "incident_link_types": sorted(LINK_KINDS),
        "excluded": ["DELETE", "risk writes", "incident create/update/status transitions", "report writes",
                     "free-form API URLs", "unknown nested update objects"],
        "bulk_max_items": 10,
    }


def v2_list_records(resource: str, page: int = 1, per_page: int = 30) -> dict:
    """Listet Assets, Aufgaben, Informationswerte, Prozesse, Maßnahmen, Risiken, Incidents oder Berichte."""
    if resource not in READ_RESOURCES:
        raise ValueError("Ressource nicht verfügbar; siehe v2_capabilities")
    body = V2API.from_env().records(resource, page=page, per_page=per_page)
    data = body["data"]
    if not isinstance(data, list):
        raise RuntimeError("API-Liste ist kein Array")
    return {"resource": resource, "client_id": EXPECTED_CLIENT_ID,
            "data": [_project(resource, r) for r in data], "meta": body.get("meta", {})}


def v2_get_record(resource: str, record_id: str) -> dict:
    """Liest einen vollständigen Datensatz per UUID; Risiken und Incidents bleiben schreibgeschützt."""
    if resource not in READ_RESOURCES:
        raise ValueError("Ressource nicht verfügbar")
    body = V2API.from_env().record(resource, record_id)
    item = body["data"]
    if not isinstance(item, dict):
        raise RuntimeError("Datensatz ist kein Objekt")
    return {"resource": resource, "client_id": EXPECTED_CLIENT_ID, "data": item}


def v2_lookup(name: str) -> dict:
    """Liest erlaubte Status-, Schutzbedarfs- und Klassifizierungs-Nachschlagewerke."""
    return {"lookup": name, "client_id": EXPECTED_CLIENT_ID,
            "data": V2API.from_env().lookup(name)["data"]}


def v2_create_record(resource: str, payload_json: str) -> dict:
    """Erstellt SOFORT einen validierten Datensatz: Assets, Tasks, Informationswerte, Prozesse, Maßnahmen.

    payload_json ist ein JSON-Objekt mit Feldern aus v2_capabilities.
    Keine separate Freigabe, keine Retries. Incidents und Risiken sind ausgeschlossen.
    """
    payload = validate_payload(resource, "create", parse_json(payload_json))
    result = V2API.from_env().create(resource, payload)["data"]
    if not isinstance(result, dict):
        raise RuntimeError("Unerwartete Erfolgsantwort; vor Retry Zustand prüfen")
    return {"created": True, "resource": resource, "client_id": EXPECTED_CLIENT_ID,
            "data": _project(resource, result)}


def v2_update_record(resource: str, record_id: str, changes_json: str) -> dict:
    """Aktualisiert SOFORT freigegebene Teilfelder eines Datensatzes (kein DELETE).

    PUT-required title/subject wird vorher per GET geladen. Mit null lassen sich nur
    laut OpenAPI nullable Felder explizit leeren. Verschachtelte Schutzbedarfs-Updates
    bleiben für die vorhandenen Spezialtools reserviert.
    """
    changes = validate_payload(resource, "update", parse_json(changes_json), partial=True)
    result = V2API.from_env().update(resource, record_id, changes)
    return {"updated": result["updated"], "resource": resource,
            "client_id": EXPECTED_CLIENT_ID, "data": _project(resource, result["data"])}


def v2_list_incident_links(incident_id: str, kind: str) -> dict:
    """Liest Incident-Verknüpfungen zu assets, measures, information-values oder business-processes."""
    result = V2API.from_env().incident_links(incident_id, kind)
    return {"client_id": EXPECTED_CLIENT_ID, "incident_id": uuid_id(incident_id),
            "kind": kind, "data": result["data"]}


def v2_link_incident(incident_id: str, kind: str, target_id: str) -> dict:
    """Verknüpft SOFORT ein Incident mit einem Asset, einer Maßnahme, Information oder einem Prozess.

    API-seitig idempotent: 201 neu, 200 bereits verknüpft. Kein DELETE/Unlink.
    """
    result = V2API.from_env().incident_links(incident_id, kind, target_id=target_id)
    return {"linked": True, "incident_id": uuid_id(incident_id), "kind": kind,
            "target_id": uuid_id(target_id), "client_id": EXPECTED_CLIENT_ID,
            "data": result["data"]}


def v2_audit_log(page: int = 1, per_page: int = 30, entity_type: str = "", action: str = "") -> dict:
    """Liest das API-Audit-Log (Administrator-Leserecht erforderlich); nur Feldnamen, keine Vorwerte."""
    body = V2API.from_env().audit_log(page=page, per_page=per_page,
                                      entity_type=entity_type, action=action)
    return {"client_id": EXPECTED_CLIENT_ID, "data": body["data"],
            "meta": body.get("meta", {})}
