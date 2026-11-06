"""Audatis MCP 2.1: read-only, typed cross-resource relationships.

Source: audatis MANAGER OpenAPI 1.3.0 (2026-11-04). Relationship arrays in
resource GET responses are read-only unless explicitly documented otherwise.
No implicit creation of asset<->information or process<->measure links.
"""
from __future__ import annotations

from collections import defaultdict, deque
from datetime import date

from task_direct import EXPECTED_CLIENT_ID
from v2_core import V2API, collect_all, resource_id

GRAPH_RESOURCES = ("assets", "information-values", "business-processes", "measures", "risks")
OWNERS = {
    "assets": "asset_owner_user_id",
    "information-values": "asset_owner_user_id",
    "business-processes": "process_owner_id",
    "measures": "responsible_user_id",
}


def v21_relationship_capabilities() -> dict:
    """Zeigt dokumentierte Beziehungen und Grenzen: frei verknüpfbare Objekte werden nicht behauptet."""
    return {
        "client_id": EXPECTED_CLIENT_ID,
        "graph_resources": list(GRAPH_RESOURCES),
        "readable_links": {
            "assets": ["parent_id", "linked_assets", "information_values", "measures", "risks"],
            "information-values": ["linked_assets"],
            "business-processes": ["parent_id", "sub_process_ids", "asset_ids", "information_value_ids", "measure_ids", "risk_ids"],
            "measures": ["asset_ids", "business_process_ids", "risk_ids"],
        },
        "supported_link_writes": ["assets.parent_id", "business-processes.parent_id", "incidents/{id}/{assets|measures|information-values|business-processes} (already in v2)"],
        "not_supported": ["arbitrary asset-to-asset POST links", "direct asset-information value link writes", "direct business-process-to-measure link writes", "risk writes", "deletions"],
        "graph_is_not": "Discovery-Scan, Netzwerk-Topologie, Risiko- oder automatische Kausalitaetsanalyse",
        "bulk_parent_write_limits": "Nur bisher elternlose Eintraege; maximal 10; execute=False als Voransicht; keine Rollbacks",
    }


def _key(resource: str, value) -> str:
    return f"{resource}:{value}"


def _ids(values):
    """Only actual stored string IDs; never follow model-generated guesses."""
    if isinstance(values, list):
        return [v for v in values if isinstance(v, str) and v.strip()]
    return []


def build_relationship_graph(api: V2API, max_pages: int = 5, *, max_edges: int = 3000) -> dict:
    """Collect actual stored relations; typed IDs prevent collisions.

    `complete` is false when any resource is paginated beyond max_pages or
    when edge output is capped. Unresolved refs are marked, never asserted
    deleted (resource might be archived or inaccessible).
    """
    if type(max_pages) is not int or not 1 <= max_pages <= 10:
        raise ValueError("max_pages muss 1..10 sein")
    if type(max_edges) is not int or not 1 <= max_edges <= 5000:
        raise ValueError("max_edges muss 1..5000 sein")
    entries, completeness = {}, {}
    nodes: dict[str, dict] = {}
    for resource in GRAPH_RESOURCES:
        rows, complete = collect_all(api, resource, max_pages=max_pages, per_page=100)
        completeness[resource] = complete
        entries[resource] = [row for row in rows if isinstance(row, dict)]
        for item in entries[resource]:
            rid = item.get("id")
            if not isinstance(rid, str) or not rid:
                continue
            label = item.get("title") if resource != "risks" else item.get("designation")
            nodes[_key(resource, rid)] = {
                "key": _key(resource, rid), "resource": resource, "id": rid,
                "title": label if isinstance(label, str) else "",
            }

    edges: dict[tuple, dict] = {}
    edge_limit_hit = False

    def add(src_resource, src_id, dst_resource, dst_id, relation, observed_in):
        nonlocal edge_limit_hit
        if not isinstance(src_id, str) or not src_id or not isinstance(dst_id, str) or not dst_id:
            return
        src, dst = _key(src_resource, src_id), _key(dst_resource, dst_id)
        label = relation if isinstance(relation, str) and relation else "linked_to"
        identity = (src, dst, label)
        if identity in edges:
            if observed_in not in edges[identity]["observed_in"]:
                edges[identity]["observed_in"].append(observed_in)
            return
        if len(edges) >= max_edges:
            edge_limit_hit = True
            return
        edges[identity] = {"source": src, "target": dst, "relation": label, "observed_in": [observed_in]}

    for asset in entries["assets"]:
        aid = asset.get("id")
        if not isinstance(aid, str):
            continue
        add("assets", asset.get("parent_id"), "assets", aid, "parent_of", "assets.parent_id")
        for link in asset.get("linked_assets") or []:
            if not isinstance(link, dict):
                continue
            other = link.get("asset_id")
            typ = str(link.get("relationship_type") or "linked_to")
            # link direction is relative to the current asset.
            if link.get("direction") not in ("incoming", "outgoing"):
                # Unknown direction must not be guessed as outgoing.
                continue
            if link.get("direction") == "incoming":
                add("assets", other, "assets", aid, f"asset_relation:{typ}", "assets.linked_assets")
            else:
                add("assets", aid, "assets", other, f"asset_relation:{typ}", "assets.linked_assets")
        for field, other_type, id_field, relation in (
            ("information_values", "information-values", "information_value_id", "asset_information"),
            ("measures", "measures", "measure_id", "asset_measure"),
            ("risks", "risks", "risk_id", "asset_risk"),
        ):
            for link in asset.get(field) or []:
                if isinstance(link, dict):
                    add("assets", aid, other_type, link.get(id_field), relation, f"assets.{field}")

    for info in entries["information-values"]:
        iid = info.get("id")
        if not isinstance(iid, str):
            continue
        for link in info.get("linked_assets") or []:
            if isinstance(link, dict):
                add("assets", link.get("asset_id"), "information-values", iid,
                    "asset_information", "information-values.linked_assets")

    for bp in entries["business-processes"]:
        pid = bp.get("id")
        if not isinstance(pid, str):
            continue
        add("business-processes", bp.get("parent_id"), "business-processes", pid,
            "process_parent_of", "business-processes.parent_id")
        for sub in _ids(bp.get("sub_process_ids")):
            add("business-processes", pid, "business-processes", sub,
                "process_parent_of", "business-processes.sub_process_ids")
        for field, typ, rel in (
            ("asset_ids", "assets", "process_asset"),
            ("information_value_ids", "information-values", "process_information"),
            ("measure_ids", "measures", "process_measure"),
            ("risk_ids", "risks", "process_risk"),
        ):
            for linked_id in _ids(bp.get(field)):
                add("business-processes", pid, typ, linked_id, rel,
                    f"business-processes.{field}")

    for measure in entries["measures"]:
        mid = measure.get("id")
        if not isinstance(mid, str):
            continue
        for field, src_type, rel in (
            ("asset_ids", "assets", "asset_measure"),
            ("business_process_ids", "business-processes", "process_measure"),
            ("risk_ids", "risks", "risk_measure"),
        ):
            for linked_id in _ids(measure.get(field)):
                add(src_type, linked_id, "measures", mid, rel, f"measures.{field}")

    unresolved = []
    for edge in edges.values():
        for endpoint in ("source", "target"):
            key = edge[endpoint]
            if key not in nodes:
                resource, rid = key.split(":", 1)
                unresolved.append({"reference": key, "from_relation": edge["relation"],
                                   "inventory_complete": completeness.get(resource, False),
                                   "note": "Ziel nicht im abgerufenen Bestand; kann archiviert, ausgeblendet oder unzugänglich sein"})
    return {
        "client_id": EXPECTED_CLIENT_ID,
        "nodes": list(nodes.values()), "edges": list(edges.values()),
        "unresolved": unresolved[:200], "unresolved_truncated": len(unresolved) > 200,
        "counts": {r: len(entries[r]) for r in GRAPH_RESOURCES},
        "inventory_complete": completeness,
        "complete": all(completeness.values()) and not edge_limit_hit,
        "edges_truncated": edge_limit_hit,
        "note": "Nur in der API bereits gespeicherte Beziehungen; kein Scan, keine Risikobewertung.",
    }


def v21_relationship_graph(max_pages: int = 5, max_edges: int = 3000) -> dict:
    """Liest den ressortübergreifenden Beziehungsgraphen ohne Datenänderungen."""
    return build_relationship_graph(V2API.from_env(), max_pages=max_pages, max_edges=max_edges)


def v21_related_records(resource: str, record_id: str, max_depth: int = 2,
                        max_pages: int = 5) -> dict:
    """Ermittelt in bis zu drei Schritten verbundene Objekte (kein kausaler Impact-Score)."""
    if resource not in GRAPH_RESOURCES:
        raise ValueError("Ressource nicht im Beziehungsgraph")
    rid = resource_id(resource, record_id)
    if type(max_depth) is not int or not 1 <= max_depth <= 3:
        raise ValueError("max_depth muss 1..3 sein")
    graph = v21_relationship_graph(max_pages=max_pages)
    if not graph["complete"]:
        raise RuntimeError("Beziehungsinventar unvollständig/gekürzt; keine verlässliche Nachbarschaftsanalyse")
    start = _key(resource, rid)
    node_index = {x["key"]: x for x in graph["nodes"]}
    if start not in node_index:
        raise ValueError("Datensatz im aktuellen Inventar nicht vorhanden")
    neighbors = defaultdict(list)
    for edge in graph["edges"]:
        a, b = edge["source"], edge["target"]
        neighbors[a].append((b, edge))
        neighbors[b].append((a, edge))
    visited = {start}
    work = deque([(start, 0)])
    related = []
    while work:
        current, depth = work.popleft()
        if depth >= max_depth:
            continue
        for neighbor, edge in neighbors[current]:
            if neighbor in visited:
                continue
            visited.add(neighbor)
            related.append({"node": node_index.get(neighbor, {"key": neighbor, "unresolved": True}),
                            "distance": depth + 1, "via": edge["relation"]})
            work.append((neighbor, depth + 1))
    return {"client_id": EXPECTED_CLIENT_ID, "start": node_index[start], "max_depth": max_depth,
            "related": related[:200], "truncated": len(related) > 200,
            "note": "Zusammenhang im dokumentierten Bestand; keine Aussage über echte Netzwerkkonnektivität oder Ausfallfolgen."}


def v21_relationship_audit(max_pages: int = 5) -> dict:
    """Heuristiken: fehlende Owner, ungeklärte Referenzen und ausstehende Reviews."""
    if type(max_pages) is not int or not 1 <= max_pages <= 10:
        raise ValueError("max_pages muss 1..10 sein")
    api = V2API.from_env()
    graph = build_relationship_graph(api, max_pages=max_pages)
    issues = []
    def issue(resource, rid, kind, **details):
        issues.append({"resource": resource, "id": rid, "issue": kind, **details})
    for resource, owner in OWNERS.items():
        rows, complete = collect_all(api, resource, max_pages=max_pages, per_page=100)
        if not complete:
            # Absence and partial data can yield misleading negative checks.
            continue
        for obj in rows:
            if not isinstance(obj, dict) or not isinstance(obj.get("id"), str):
                continue
            rid = obj["id"]
            if obj.get(owner) is None:
                issue(resource, rid, "missing_owner")
            due = obj.get("next_review_at")
            if isinstance(due, str) and len(due) >= 10:
                try:
                    if date.fromisoformat(due[:10]) < date.today():
                        issue(resource, rid, "review_past_due", due=due[:10])
                except ValueError:
                    pass
            if resource == "assets":
                protection = obj.get("protection_needs")
                if isinstance(protection, dict) and any(protection.get(k) is None for k in ("confidentiality", "integrity", "availability")):
                    issue(resource, rid, "effective_cia_missing_or_incomplete")
            elif resource == "information-values":
                protection = obj.get("protection_needs")
                if isinstance(protection, dict):
                    missing = [k for k in ("confidentiality", "integrity", "availability")
                               if not isinstance(protection.get(k), dict) or protection[k].get("level") in (None, "not_defined")]
                    if missing:
                        issue(resource, rid, "information_cia_incomplete", dimensions=missing)
    for item in graph["unresolved"]:
        if item["inventory_complete"]:
            issue(item["reference"].split(":",1)[0], item["reference"].split(":",1)[1],
                  "unresolved_relation_reference", relation=item["from_relation"])
    return {
        "client_id": EXPECTED_CLIENT_ID, "inventory_complete": graph["inventory_complete"],
        "issue_count": len(issues), "issues": issues[:200], "truncated": len(issues) > 200,
        "note": "Hinweise auf Dokumentationsqualität, keine Compliance-Feststellung. Verwaiste Referenzen nicht automatisch löschen.",
    }
