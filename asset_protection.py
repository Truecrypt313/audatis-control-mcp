"""MCP tools for audatis MANAGER asset protection needs (OpenAPI 1.3.0).

Register with the same MCPServer in server.py:
    from asset_protection import list_asset_protection_levels, set_asset_protection_needs
    mcp.tool()(list_asset_protection_levels)
    mcp.tool()(set_asset_protection_needs)

Works only in the already configured fixed test client, using the existing
local write-token arrangement. Never logs or returns the token.
"""
from __future__ import annotations

from typing import Any

from asset_management import get_asset, _uuid
from asset_owner_management import _api_call
from task_direct import EXPECTED_CLIENT_ID

# Sentinel values avoid unintentionally clearing fields when the LLM leaves
# an optional argument unset. -2 explicitly clears the selected override.
UNCHANGED = -1
CLEAR = -2
_OVERRIDES = {
    "confidentiality": "confidentiality_override",
    "integrity": "integrity_override",
    "availability": "availability_override",
}
_EDITABLE_FIELDS = (
    "classification", "confidentiality_override", "integrity_override",
    "availability_override", "criticality_override",
)


def list_asset_protection_levels() -> dict[str, Any]:
    """Liest die aktiven Schutzbedarfsstufen (numerischer level und Name).

    Diese Stufen müssen vor einer erstmaligen Schutzbedarf-Zuweisung abgefragt
    werden; die Zahlen werden NICHT durch die KI geraten.
    """
    result = _api_call(
        "GET", f"/api/v1/clients/{EXPECTED_CLIENT_ID}/assets/protection-levels"
    )
    entries = result["data"]
    if not isinstance(entries, list):
        raise RuntimeError("Unerwartete Liste der Schutzbedarfsstufen")
    return {
        "client_id": EXPECTED_CLIENT_ID,
        "data": [
            {
                "level": e["level"], "name": e["name"],
                "id": e["id"], "is_active": e["is_active"],
            }
            for e in entries
            if isinstance(e, dict) and e.get("is_active") is True
        ],
    }


def _valid_levels() -> set[int]:
    levels: set[int] = set()
    for item in list_asset_protection_levels()["data"]:
        value = item.get("level")
        if type(value) is int:
            levels.add(value)
    if not levels:
        raise RuntimeError("Keine aktiven Schutzbedarfsstufen gefunden; kein Update")
    return levels


def _check_level(name: str, value: int, known: set[int]) -> None:
    if type(value) is not int:
        raise ValueError(f"{name} muss eine ganze Zahl sein")
    if value not in (UNCHANGED, CLEAR) and value not in known:
        raise ValueError(
            f"Ungültiger {name}-Wert {value}. Zulässige Schutzbedarfsstufen: {sorted(known)}. "
            "-1=unverändert, -2=Override entfernen"
        )


def set_asset_protection_needs(
    asset_id: str,
    confidentiality: int = UNCHANGED,
    integrity: int = UNCHANGED,
    availability: int = UNCHANGED,
) -> dict[str, Any]:
    """Setzt C/I/A-Overrides eines Assets SOFORT in audatisManager.

    Werte: numerischer `level` aus list_asset_protection_levels().
    -1 bedeutet unverändert; -2 löscht einen vorhandenen manuellen Override.
    Nur ausdrücklich genannte Dimensionen werden angepasst.
    Die API kann niedrigere Overrides ignorieren, wenn eine höhere Stufe
    aus verknüpften Informationswerten abgeleitet wurde.
    """
    asset_id = _uuid(asset_id, "asset_id")
    requested = {
        "confidentiality": confidentiality,
        "integrity": integrity,
        "availability": availability,
    }
    if all(value == UNCHANGED for value in requested.values()):
        raise ValueError("Mindestens einen Schutzbedarfswert angeben")

    known = _valid_levels()
    for name, value in requested.items():
        _check_level(name, value, known)

    current = get_asset(asset_id)["asset"]
    if not isinstance(current, dict) or not isinstance(current.get("protection_needs"), dict):
        raise RuntimeError("Asset ohne auswertbare protection_needs; Update abgebrochen")
    title = current.get("title")
    if not isinstance(title, str) or not title.strip():
        raise RuntimeError("Assettitel fehlt; Update abgebrochen")

    old_needs = current["protection_needs"]
    # Preserve all other writable protection-needs fields explicitly. Some
    # endpoints replace nested objects rather than merging per field.
    preserved = {k: old_needs.get(k) for k in _EDITABLE_FIELDS}
    changed = []
    for name, value in requested.items():
        if value == UNCHANGED:
            continue
        field = _OVERRIDES[name]
        new_value = None if value == CLEAR else value
        if preserved[field] != new_value:
            preserved[field] = new_value
            changed.append(field)

    if not changed:
        return {
            "updated": False, "client_id": EXPECTED_CLIENT_ID,
            "asset_id": asset_id, "reason": "Werte bereits identisch",
            "protection_needs": old_needs,
        }

    result = _api_call(
        "PUT",
        f"/api/v1/clients/{EXPECTED_CLIENT_ID}/assets/{asset_id}",
        payload={"title": title, "protection_needs": preserved},
    )
    saved = result["data"]
    if not isinstance(saved, dict) or not isinstance(saved.get("protection_needs"), dict):
        raise RuntimeError("Unerwartete API-Antwort nach PUT; Asset vor einem Retry prüfen")
    after = saved["protection_needs"]
    not_applied = [name for name in changed if after.get(name) != preserved[name]]
    return {
        "updated": True,
        "client_id": EXPECTED_CLIENT_ID,
        "asset_id": asset_id,
        "title": saved.get("title"),
        "changed_override_fields": changed,
        "override_fields_not_applied": not_applied,
        "protection_needs_before": old_needs,
        "protection_needs_after": after,
        "note": (
            "Die API ignoriert Overrides unterhalb der aus verknüpften Informationswerten "
            "abgeleiteten Stufe. C/I/A in protection_needs_after sind die effektiven Werte."
        ),
    }
