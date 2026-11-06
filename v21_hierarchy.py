"""Conservative, tenant-bound, preview-first hierarchy updates.

Only documented parent_id on assets / business-processes; no generic link APIs.
Never unparent/reparent existing records, no deletes, no retries, no rollback.
"""
from __future__ import annotations

from v2_core import V2API, collect_all, parse_json, resource_id, validate_payload
from task_direct import EXPECTED_CLIENT_ID

_ALLOWED = ("assets", "business-processes")
_MAX = 10


def _parse(resource: str, items_json: str):
    if resource not in _ALLOWED:
        raise ValueError("Nur assets oder business-processes erlaubt")
    rows = parse_json(items_json, expect=list)
    if not 1 <= len(rows) <= _MAX:
        raise ValueError("Es sind 1 bis 10 Hierarchieänderungen erlaubt")
    seen = set()
    changes = []
    for obj in rows:
        if type(obj) is not dict or set(obj) != {"record_id", "parent_id"}:
            raise ValueError("Jeder Eintrag benötigt genau record_id und parent_id")
        child = resource_id(resource, obj["record_id"])
        parent = resource_id(resource, obj["parent_id"])
        if child == parent:
            raise ValueError("Ein Eintrag darf nicht sein eigenes Parent sein")
        if child in seen:
            raise ValueError("Doppelte record_id im Paket")
        seen.add(child)
        validate_payload(resource, "update", {"parent_id": parent}, partial=True)
        changes.append((child, parent))
    return changes


def _load_and_plan(api: V2API, resource: str, changes, max_pages: int):
    rows, complete = collect_all(api, resource, max_pages=max_pages, per_page=100)
    if not complete:
        raise RuntimeError("Bestand unvollständig; Hierarchieänderung abgebrochen")
    lookup = {}
    for row in rows:
        if not isinstance(row, dict) or not row.get("id"):
            raise RuntimeError("Ungültiger Eintrag in der Bestandsliste")
        rid = resource_id(resource, row["id"])
        if rid in lookup:
            raise RuntimeError("Doppelte ID in der Bestandsliste")
        lookup[rid] = row
    proposed = {}
    plan = []
    for child, parent in changes:
        if child not in lookup or parent not in lookup:
            raise ValueError("Kind oder Parent nicht in der vollständigen Bestandsliste")
        old = lookup[child]
        target = lookup[parent]
        if old.get("is_archived") is True or target.get("is_archived") is True:
            raise ValueError("Archivierte Ressourcen dürfen nicht umgehängt werden")
        if resource == "assets" and target.get("is_group") is not True:
            raise ValueError(f"Asset-Parent {parent} muss is_group=true besitzen")
        old_parent = old.get("parent_id")
        if old_parent and resource_id(resource, old_parent) != parent:
            raise ValueError(f"Vorhandenes Parent bei {child}: keine automatische Umhängung")
        if not isinstance(old.get("title"), str) or not old["title"].strip():
            raise RuntimeError("Titel fehlt; kein sicherer PUT möglich")
        proposed[child] = parent
        plan.append({"record_id": child, "parent_id": parent, "current_parent_id": old_parent,
                     "action": "unchanged" if old_parent == parent else "set_parent"})

    # The intended graph includes ALL current parent references, plus proposed ones.
    parents = {rid: resource_id(resource, row["parent_id"]) if row.get("parent_id") else None
               for rid, row in lookup.items()}
    parents.update(proposed)
    for child in proposed:
        visited = set()
        current = child
        while current is not None:
            if current in visited:
                raise ValueError("Zyklische Hierarchie erkannt: keine Änderung")
            visited.add(current)
            current = parents.get(current)
    return lookup, plan


def v21_bulk_set_parent(resource: str, items_json: str, execute: bool = False,
                        max_pages: int = 5) -> dict:
    """Setzt fuer bis zu 10 bisher elternlose Assets/Prozesse einen Parent; Dry-run Standard.

    JSON: [{"record_id":"...", "parent_id":"..."}]. Auch die Vorschau
    liest den Bestand, schreibt jedoch nichts. Alle Kind-/Parent-IDs müssen
    im vollständig geladenen Mandanten-Inventar existieren. Asset-Parent muss
    als Gruppe markiert sein. Bestehendes Parent wird niemals ersetzt.
    """
    if type(execute) is not bool:
        raise ValueError("execute muss true oder false sein")
    if type(max_pages) is not int or not 1 <= max_pages <= 10:
        raise ValueError("max_pages muss 1..10 sein")
    changes = _parse(resource, items_json)
    api = V2API.from_env()
    before, plan = _load_and_plan(api, resource, changes, max_pages)
    if not execute:
        return {"client_id": EXPECTED_CLIENT_ID, "resource": resource, "execute": False,
                "verified_inventory": True, "count": len(plan), "preview": plan,
                "notice": "Nur GET-Aufrufe; kein PUT. execute=true schreibt direkt, ohne erneute Freigabe."}
    results = []
    for index, entry in enumerate(plan):
        child, parent = entry["record_id"], entry["parent_id"]
        if entry["action"] == "unchanged":
            results.append({"index": index, "record_id": child, "updated": False})
            continue
        try:
            # Last read avoids overwriting unrelated concurrent changes to title/parent.
            current = api.record(resource, child)["data"]
            previous = before[child]
            if (not isinstance(current, dict) or current.get("title") != previous.get("title")
                or current.get("parent_id") != previous.get("parent_id")):
                raise RuntimeError("Datensatz hat sich seit Vorprüfung verändert; Stopp")
            api.update(resource, child, {"parent_id": parent}, current=current)
            after = api.record(resource, child)["data"]
            if not isinstance(after, dict) or after.get("parent_id") != parent:
                raise RuntimeError("Schreibantwort nicht verifizierbar; Zustand vor erneutem Versuch prüfen")
            results.append({"index": index, "record_id": child, "updated": True,
                            "verified_parent_id": parent})
        except (ValueError, RuntimeError) as exc:
            return {"client_id": EXPECTED_CLIENT_ID, "execute": True, "completed": False,
                    "resource": resource, "results": results, "stopped_at_index": index,
                    "error": str(exc), "note": "Teilerfolg möglich; kein Rollback und kein automatischer Retry."}
    return {"client_id": EXPECTED_CLIENT_ID, "execute": True, "completed": True,
            "resource": resource, "results": results,
            "note": "Nur dokumentiertes parent_id geändert; kein allgemeines Link-Management."}
