"""Bounded non-transactional bulk execution with full preflight validation.

execute=False previews; execute=True writes directly, without manual per-item approval.
Write failures STOP further writes. No automatic retries or rollbacks.
"""
from __future__ import annotations

from task_direct import EXPECTED_CLIENT_ID
from v2_core import V2API, WRITE_RESOURCES, parse_json, validate_payload, resource_id, collect_all

MAX_ITEMS = 10


def _items(raw: str) -> list[dict]:
    arr = parse_json(raw, expect=list)
    if not 1 <= len(arr) <= MAX_ITEMS:
        raise ValueError(f"Bulk erlaubt 1 bis {MAX_ITEMS} Einträge")
    if any(type(x) is not dict for x in arr):
        raise ValueError("Alle Einträge müssen JSON-Objekte sein")
    return arr


def _name(resource: str, record: dict) -> str:
    value = record.get("subject" if resource == "tasks" else "title")
    return " ".join(value.strip().lower().split()) if isinstance(value, str) else ""


def _preflight_create(api: V2API, resource: str, entries: list[dict], check_existing: bool) -> None:
    keys = [_name(resource, x) for x in entries]
    if any(not k for k in keys) or len(set(keys)) != len(keys):
        raise ValueError("Leere oder doppelte Titel/Betreffe im Bulk-Paket")
    if not check_existing:
        return
    existing, complete = collect_all(api, resource, max_pages=10, per_page=200)
    if not complete:
        raise RuntimeError("Bestandsprüfung unvollständig (>2000 Einträge): Bulk-Erstellung abgebrochen")
    known = {_name(resource, x) for x in existing}
    overlaps = sorted(set(keys) & known)
    if overlaps:
        raise ValueError("Mögliche Dubletten im Bestand (keine Erstellung): " + ", ".join(overlaps[:5]))


def v2_bulk_create_records(resource: str, items_json: str, execute: bool = False,
                           check_existing: bool = True) -> dict:
    """Erstellt in einem Durchlauf maximal 10 Assets, Aufgaben, Informationen, Prozesse oder Maßnahmen.

    Alle Einträge werden VOR einem Schreibzugriff validiert. Bei execute=False nur
    Planvorschau; execute=True führt ohne Einzelbestätigung aus. Default prüft
    Dubletten anhand von Titel/Betreff über die vollständig paginierte API-Liste.
    """
    if resource not in WRITE_RESOURCES:
        raise ValueError("Ressource nicht für Bulk-Schreiben freigegeben")
    entries = [validate_payload(resource, "create", item) for item in _items(items_json)]
    keys = [_name(resource, x) for x in entries]
    if any(not k for k in keys) or len(set(keys)) != len(keys):
        raise ValueError("Leere oder doppelte Titel/Betreffe im Paket")
    if not execute:
        return {"execute": False, "resource": resource, "client_id": EXPECTED_CLIENT_ID,
                "count": len(entries), "check_existing_on_execute": check_existing,
                "preview": [{"name": _name(resource, x), "fields": sorted(x)} for x in entries],
                "notice": "Keine API-Aufrufe und keine Änderungen. execute=True startet Vorprüfung und Schreibzugriffe."}
    api = V2API.from_env()
    _preflight_create(api, resource, entries, check_existing)
    written = []
    for index, data in enumerate(entries):
        try:
            response = api.create(resource, data)["data"]
            if not isinstance(response, dict) or not response.get("id"):
                raise RuntimeError("API-Erstellungsantwort ohne ID; Status vor Retry prüfen")
            written.append({"index": index, "id": response["id"], "name": _name(resource, response)})
        except Exception as exc:
            return {"execute": True, "completed": False, "client_id": EXPECTED_CLIENT_ID,
                    "resource": resource, "created": written, "stopped_at_index": index,
                    "error": str(exc), "note": "Teilerfolg möglich; keine automatische Wiederholung oder Rücknahme."}
    return {"execute": True, "completed": True, "resource": resource,
            "client_id": EXPECTED_CLIENT_ID, "created": written}


def _preflight_update(api: V2API, resource: str, entries: list[dict]) -> list[dict]:
    planned = []
    keys = [resource_id(resource, x["record_id"]) for x in entries]
    if len(set(keys)) != len(keys):
        raise ValueError("Doppelte record_id im Bulk-Update")
    for index, (rid, entry) in enumerate(zip(keys, entries)):
        old = api.record(resource, rid)["data"]
        if not isinstance(old, dict):
            raise RuntimeError(f"GET für Datensatz {index} ist kein Objekt")
        if old.get("id") and resource_id(resource, old["id"]) != rid:
            raise RuntimeError("GET-Objekt-ID stimmt nicht überein")
        changes = entry["changes"]
        new = {k: v for k, v in changes.items() if old.get(k) != v}
        identity = "subject" if resource == "tasks" else "title"
        if not isinstance(old.get(identity), str) or not old[identity].strip():
            raise RuntimeError("Originaltitel fehlt; kein Bulk-Update")
        if new:
            validate_payload(resource, "update", {identity: old[identity], **new})
        planned.append({"record_id": rid, "before": old, "changes": new})
    return planned


def v2_bulk_update_records(resource: str, items_json: str, execute: bool = False) -> dict:
    """Bulk-Update mit GET-Vorabfrage, validierten Änderungen und Teilfehler-Bericht.

    JSON-Array: [{"record_id":"UUID", "changes":{"status":"in_progress"}}].
    Bei execute=False nur lokale Validierung; execute=True prüft ALLE Datensätze
    vor der ersten Änderung. Keine Transaktion / automatische Rücknahme.
    """
    if resource not in WRITE_RESOURCES:
        raise ValueError("Ressource nicht für Bulk-Update freigegeben")
    entries = _items(items_json)
    checked = []
    for item in entries:
        if set(item) != {"record_id", "changes"}:
            raise ValueError("Jeder Eintrag benötigt ausschließlich record_id und changes")
        rid = resource_id(resource, item["record_id"])
        changes = validate_payload(resource, "update", item["changes"], partial=True)
        checked.append({"record_id": rid, "changes": changes})
    if len({x["record_id"] for x in checked}) != len(checked):
        raise ValueError("Doppelte record_id im Update-Paket")
    if not execute:
        return {"execute": False, "resource": resource, "client_id": EXPECTED_CLIENT_ID,
                "count": len(checked), "preview": [{"record_id": x["record_id"],
                        "changed_fields": sorted(x["changes"])} for x in checked]}
    api = V2API.from_env()
    planned = _preflight_update(api, resource, checked)
    results = []
    for index, item in enumerate(planned):
        if not item["changes"]:
            results.append({"index": index, "record_id": item["record_id"], "updated": False})
            continue
        try:
            # Same current data from preflight avoids a second, potentially inconsistent GET.
            body = api.update(resource, item["record_id"], item["changes"], current=item["before"])
            results.append({"index": index, "record_id": item["record_id"],
                            "updated": body["updated"]})
        except Exception as exc:
            return {"execute": True, "completed": False, "client_id": EXPECTED_CLIENT_ID,
                    "resource": resource, "results": results, "stopped_at_index": index,
                    "error": str(exc), "note": "Teilerfolg möglich, keine Wiederholung; geänderte Datensätze prüfen."}
    return {"execute": True, "completed": True, "resource": resource,
            "client_id": EXPECTED_CLIENT_ID, "results": results}
