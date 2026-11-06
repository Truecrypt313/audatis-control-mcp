"""Read-only inventory, asset graph and documentation quality checks.

These are heuristics on API data, not automatic risk classifications.
No API writes or inferred relationship creation.
"""
from __future__ import annotations

from collections import defaultdict
from datetime import date

from v2_core import V2API, collect_all
from task_direct import EXPECTED_CLIENT_ID


def _get(api, resource, max_pages):
    return collect_all(api, resource, max_pages=max_pages, per_page=100)


def v2_inventory_snapshot(max_pages: int = 5) -> dict:
    """Erfasst ein begrenztes, datensparsames Inventar-Snapshot ohne Schreibzugriffe.

    Counts are lower bounds when complete=False. No claim of exhaustive discovery.
    """
    api = V2API.from_env()
    result = {}
    for res in ("assets", "information-values", "business-processes", "measures", "risks", "tasks", "incidents"):
        records, complete = _get(api, res, max_pages)
        result[res] = {"count": len(records), "complete": complete}
    return {"client_id": EXPECTED_CLIENT_ID, "inventory": result,
            "note": "API-basierte Bestandsaufnahme; keine aktive Netzwerk-Discovery. Bei complete=false nur Untergrenzen."}


def v2_asset_graph(max_pages: int = 5) -> dict:
    """Ermittelt bestehende Asset-Hierarchien und bereits gespeicherte Verknüpfungen.

    'linked_assets' are relationships, not automatically an inferred network dependency.
    No new relation is written; unsupported relationship-create endpoints are not invented.
    """
    api = V2API.from_env()
    records, complete = _get(api, "assets", max_pages)
    nodes, edges = [], []
    seen = set()
    for item in records:
        if not isinstance(item, dict) or not item.get("id"):
            continue
        aid = item["id"]
        nodes.append({"id": aid, "title": item.get("title"), "category_id": item.get("category_id"),
                      "type_id": item.get("type_id"), "asset_owner_user_id": item.get("asset_owner_user_id")})
        parent = item.get("parent_id")
        if parent:
            key = (parent, aid, "parent_of")
            if key not in seen:
                seen.add(key)
                edges.append({"source": parent, "target": aid, "relation": "parent_of"})
        for link in item.get("linked_assets") or []:
            if not isinstance(link, dict) or not link.get("asset_id"):
                continue
            target = link["asset_id"]
            direction = link.get("direction")
            source, dest = (target, aid) if direction == "incoming" else (aid, target)
            typ = link.get("relationship_type") or "linked"
            key = (source, dest, typ)
            if key not in seen:
                seen.add(key)
                edges.append({"source": source, "target": dest, "relation": typ,
                              "reported_direction": direction})
    return {"client_id": EXPECTED_CLIENT_ID, "complete": complete,
            "nodes": nodes, "edges": edges,
            "note": "Graph entspricht vorhandenen API-Hierarchien/Beziehungen; keine automatische Netzwerk-Topologie."}


def v2_documentation_gaps(max_pages: int = 5) -> dict:
    """Markiert potenzielle Dokumentationslücken in Assets, Informationen, Prozessen, Maßnahmen.

    Diese Hinweise sind KEINE Compliance-Feststellung und KEINE Risikoeinstufung.
    """
    api = V2API.from_env()
    issues, coverage = [], {}
    specs = {
        "assets": "asset_owner_user_id",
        "information-values": "asset_owner_user_id",
        "business-processes": "process_owner_id",
        "measures": "responsible_user_id",
    }
    for resource, owner in specs.items():
        records, complete = _get(api, resource, max_pages)
        coverage[resource] = {"records": len(records), "complete": complete}
        for x in records:
            if not isinstance(x, dict):
                continue
            rid = x.get("id")
            if not rid:
                continue
            name = x.get("title")
            if x.get(owner) is None:
                issues.append({"resource": resource, "id": rid, "title": name, "issue": "missing_owner"})
            if resource == "assets":
                needs = x.get("protection_needs") or {}
                if any(needs.get(k) is None for k in ("confidentiality", "integrity", "availability")):
                    issues.append({"resource": resource, "id": rid, "title": name, "issue": "cia_incomplete"})
                if not (x.get("information_values") or []):
                    issues.append({"resource": resource, "id": rid, "title": name, "issue": "no_linked_information"})
                if not (x.get("measures") or []):
                    issues.append({"resource": resource, "id": rid, "title": name, "issue": "no_linked_measure"})
            if resource == "business-processes" and not (x.get("asset_ids") or []):
                issues.append({"resource": resource, "id": rid, "title": name, "issue": "no_linked_asset"})
            next_review = x.get("next_review_at")
            if isinstance(next_review, str) and len(next_review) >= 10:
                try:
                    if date.fromisoformat(next_review[:10]) < date.today():
                        issues.append({"resource": resource, "id": rid, "title": name, "issue": "review_past_due"})
                except ValueError:
                    pass
    return {"client_id": EXPECTED_CLIENT_ID, "coverage": coverage,
            "issue_count": len(issues), "issues": issues[:200], "truncated": len(issues) > 200,
            "note": "Heuristik aus gespeicherten API-Feldern, keine normative Pflicht oder Risikobewertung."}


def v2_duplicate_tasks(max_pages: int = 5) -> dict:
    """Sucht gleiche normalisierte Aufgabenbetreffe im paginierten Bestand (nur Lesen)."""
    api = V2API.from_env()
    records, complete = _get(api, "tasks", max_pages)
    grouped = defaultdict(list)
    for x in records:
        if not isinstance(x, dict):
            continue
        subject = x.get("subject")
        if isinstance(subject, str) and subject.strip():
            key = " ".join(subject.lower().split())
            grouped[key].append({"id": x.get("id"), "subject": subject,
                                 "status": x.get("status"), "due_date": x.get("due_date")})
    duplicates = [{"normalized_subject": name, "tasks": group}
                  for name, group in grouped.items() if len(group) > 1]
    return {"client_id": EXPECTED_CLIENT_ID, "complete": complete,
            "duplicate_groups": duplicates[:100], "truncated": len(duplicates) > 100,
            "note": "Gleicher Betreff bedeutet nicht zwingend echte Dublette."}
