"""Small offline sample and pure plan builder; never calls an API or writes assets."""
from __future__ import annotations

from uuid import UUID

from .model import empty_bundle, source, validate_bundle

DEMO_ASSETS = (
    ("DEMO-FW-01", "Netzwerk & Infrastruktur", "Firewall"),
    ("DEMO-SRV-01", "Systeme", "Server"),
    ("DEMO-WST-01", "Systeme", "Client / Arbeitsplatz"),
)


def _normalized(text):
    return " ".join(text.casefold().split()) if isinstance(text, str) else ""


def creation_plan(categories, types_by_category, existing_assets, *, inventory_complete):
    """Use supplied lookup IDs only; ambiguous/missing lookups or inventory stop planning."""
    if inventory_complete is not True:
        raise ValueError("Bestandsprüfung unvollständig; keine Erstellung planen")
    if (not isinstance(categories, list) or not isinstance(existing_assets, list)
            or not isinstance(types_by_category, dict)
            or any(not isinstance(row, dict) for row in categories + existing_assets)
            or any(not isinstance(rows, list) or any(not isinstance(row, dict) for row in rows)
                   for rows in types_by_category.values())):
        raise ValueError("Lookup oder Bestand nicht auswertbar; keine Erstellung planen")
    if any(not isinstance(row.get("title"), str) or not row["title"].strip() for row in existing_assets):
        raise ValueError("Bestandsnamen nicht vollständig überprüfbar; keine Erstellung planen")
    existing = {_normalized(row.get("title")) for row in existing_assets}
    if any(_normalized(title) in existing for title, _, _ in DEMO_ASSETS):
        raise ValueError("Mindestens ein Demo-Name existiert bereits; keine Dublette planen")
    items = []
    for title, category_name, type_name in DEMO_ASSETS:
        matches = [c for c in categories if _normalized(c.get("name")) == _normalized(category_name)
                   and c.get("is_active") is True]
        if len(matches) != 1 or not isinstance(matches[0].get("id"), str):
            raise ValueError("Kategorie fehlt oder ist nicht eindeutig; Lookup fachlich klären")
        category = matches[0]["id"]
        matches = [t for t in types_by_category.get(category, [])
                   if _normalized(t.get("name")) == _normalized(type_name) and t.get("is_active") is True
                   and t.get("category_id") == category]
        if len(matches) != 1 or not isinstance(matches[0].get("id"), str):
            raise ValueError("Asset-Typ fehlt oder ist nicht eindeutig; Lookup fachlich klären")
        items.append({"title": title, "category_id": category, "type_id": matches[0]["id"]})
    return items


def asset_demo_bundle():
    """Three synthetic assets; legacy multi-resource fixtures remain separately available."""
    uid = lambda number: str(UUID(int=number))
    bundle = empty_bundle("Synthetische Asset-Demo", "2026-11-14", "2026-11-14T10:00:00+01:00",
                          "synthetic:asset-demo", synthetic=True,
                          scope={"name": "Drei synthetische Test-Assets",
                                 "object_ids": {"assets": [uid(n) for n in (301, 302, 303)]}})
    for name, data in (
        ("asset_protection_levels", {"levels": [{"level": 1, "name": "Normal"}, {"level": 2, "name": "Hoch"}]}),
        ("asset_statuses", {"statuses": [{"id": uid(401), "name": "Aktiv", "is_archive": False}]}),
    ):
        entry = source("lookup_values", {"name": name}, bundle["context"]["client_reference"], data)
        bundle["sources"].append(entry)
        bundle["references"][name] = entry["source_id"]
    for index, (title, _, _) in enumerate(DEMO_ASSETS, 1):
        record = {
            "id": uid(300 + index), "title": title, "status_id": uid(401), "is_archived": False,
            "description": None if index == 1 else "Ausschließlich synthetisches Test-Asset.",
            "asset_owner_user_id": None if index == 1 else 90000 + index,
            "protection_needs": {d: None if index == 1 else 1
                                for d in ("confidentiality", "integrity", "availability")},
            "information_values": [], "measures": [], "linked_assets": [], "parent_id": None,
        }
        entry = source("get_record", {"resource": "assets", "record_id": record["id"]},
                       bundle["context"]["client_reference"], record)
        bundle["sources"].append(entry)
        bundle["resources"]["assets"]["records"].append(entry["source_id"])
        bundle["resources"]["assets"]["source_ids"].append(entry["source_id"])
    bundle["resources"]["assets"].update(state="complete", reason="Vollständige synthetische Primärauswahl")
    validate_bundle(bundle)
    return bundle
