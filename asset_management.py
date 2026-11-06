"""audatis MANAGER MCP asset tools for the fixed TEST client (OpenAPI 1.3.0).

Register in server.py:
    from asset_management import (
        get_asset, list_asset_categories, list_asset_types, create_asset
    )
    for tool in (get_asset, list_asset_categories, list_asset_types, create_asset):
        mcp.tool()(tool)

GET/POST only; no update/delete. Reuses the existing locally stored write token.
"""
from __future__ import annotations

import os
from uuid import UUID

import httpx

from audatis_api import _origin
from task_direct import EXPECTED_CLIENT_ID, _write_token


_ASSET_FIELDS = (
    "id", "title", "description", "category_id", "type_id", "status_id",
    "asset_owner_user_id", "additional_responsible_user_ids", "tag_ids",
    "is_group", "parent_id", "is_shared", "is_archived", "country_ids",
    "custom_fields", "created_at", "updated_at", "ai", "lifecycle",
    "protection_needs", "linked_assets", "information_values",
    "service_providers", "measures", "risks",
)


def _uuid(value: str, name: str) -> str:
    """Force resource IDs to canonical UUIDs; never accept an arbitrary URL path."""
    if not isinstance(value, str):
        raise ValueError(f"{name} muss eine UUID sein")
    try:
        return str(UUID(value))
    except ValueError as exc:
        raise ValueError(f"{name} muss eine gültige UUID sein") from exc


def _settings() -> tuple[str, str]:
    if os.environ.get("AUDATIS_CLIENT_ID") != str(EXPECTED_CLIENT_ID):
        raise RuntimeError("MCP nicht für den erwarteten Testmandanten konfiguriert")
    base_url = _origin(os.environ.get("AUDATIS_BASE_URL", ""))
    return base_url, _write_token()


def _request(method: str, path: str, *, payload: dict | None = None) -> dict:
    """Fixed author-supplied paths only. No redirect, proxy, retries or token logging."""
    if method not in ("GET", "POST"):
        raise ValueError("HTTP-Methode nicht freigegeben")
    base_url, token = _settings()
    kwargs = {"json": payload} if payload is not None else {}
    try:
        with httpx.Client(
            base_url=base_url,
            timeout=20.0,
            follow_redirects=False,
            trust_env=False,
        ) as client:
            response = client.request(
                method, path,
                headers={
                    "Authorization": f"Bearer {token}",
                    "Accept": "application/json",
                },
                **kwargs,
            )
    except httpx.RequestError as exc:
        raise RuntimeError(
            "Netzwerkfehler. Bei POST vor erneutem Versuch in der Assetliste "
            "prüfen, ob das Asset möglicherweise bereits erstellt wurde."
        ) from exc

    expected_status = 201 if method == "POST" else 200
    if response.status_code != expected_status:
        hints = {
            401: "Token ungültig oder abgelaufen",
            403: "Token-Scope, Modul- und Mandantenrechte prüfen",
            404: "Ressource oder Mandant nicht gefunden",
            422: "API-Validierung fehlgeschlagen; Kategorie/Typ/Feldwerte prüfen",
        }
        raise RuntimeError(
            f"audatis HTTP {response.status_code}: "
            f"{hints.get(response.status_code, 'Request fehlgeschlagen')}"
        )
    try:
        body = response.json()
        result = body["data"]
    except (ValueError, KeyError, TypeError) as exc:
        raise RuntimeError(
            "Erfolgsstatus, aber unerwartete JSON-Antwort; vor Wiederholung "
            "den Zustand in audatisManager prüfen."
        ) from exc
    if not isinstance(result, (dict, list)):
        raise RuntimeError("Unerwartetes API-Antwortformat")
    return result


def list_asset_categories() -> dict:
    """Liest aktive Asset-Kategorien samt IDs für die spätere Asset-Erstellung."""
    data = _request("GET", f"/api/v1/clients/{EXPECTED_CLIENT_ID}/assets/categories")
    if not isinstance(data, list):
        raise RuntimeError("Kategorien-Antwort ist keine Liste")
    return {
        "client_id": EXPECTED_CLIENT_ID,
        "data": [
            {"id": entry.get("id"), "name": entry.get("name"),
             "is_active": entry.get("is_active")}
            for entry in data if isinstance(entry, dict)
        ],
    }


def list_asset_types(category_id: str) -> dict:
    """Liest aktive Asset-Typen der angegebenen Kategorie (UUID)."""
    category_id = _uuid(category_id, "category_id")
    data = _request(
        "GET",
        f"/api/v1/clients/{EXPECTED_CLIENT_ID}/assets/categories/{category_id}/types",
    )
    if not isinstance(data, list):
        raise RuntimeError("Asset-Typen-Antwort ist keine Liste")
    return {
        "client_id": EXPECTED_CLIENT_ID,
        "category_id": category_id,
        "data": [
            {"id": item.get("id"), "name": item.get("name"),
             "category_id": item.get("category_id"),
             "is_active": item.get("is_active")}
            for item in data if isinstance(item, dict)
        ],
    }


def get_asset(asset_id: str) -> dict:
    """Liest ein einzelnes Asset, einschließlich Schutzbedarf und Verknüpfungen; ohne Änderung."""
    asset_id = _uuid(asset_id, "asset_id")
    data = _request("GET", f"/api/v1/clients/{EXPECTED_CLIENT_ID}/assets/{asset_id}")
    if not isinstance(data, dict):
        raise RuntimeError("Asset-Antwort ist kein Objekt")
    asset = {key: data.get(key) for key in _ASSET_FIELDS}
    risks = asset.get("risks")
    return {
        "client_id": EXPECTED_CLIENT_ID,
        "asset": asset,
        "linked_risks_count": len(risks) if isinstance(risks, list) else None,
    }


def create_asset(title: str, category_id: str, type_id: str = "") -> dict:
    """Erstellt SOFORT ein Asset im Testmandanten ohne manuelle Freigabe.

    Vorher list_asset_categories aufrufen, um eine gültige category_id zu wählen.
    Für den optionalen type_id-Wert list_asset_types(category_id) verwenden.
    OpenAPI v1.3.0: POST AssetCreateRequest erlaubt title, category_id, type_id,
    aber KEIN description-Feld. Keine automatischen Wiederholungen.
    """
    if not isinstance(title, str) or not 1 <= len(title.strip()) <= 255:
        raise ValueError("title muss 1 bis 255 Zeichen haben")
    category_id = _uuid(category_id, "category_id")
    if not isinstance(type_id, str):
        raise ValueError("type_id muss eine UUID oder leer sein")

    payload = {"title": title.strip(), "category_id": category_id}
    if type_id:
        payload["type_id"] = _uuid(type_id, "type_id")

    data = _request("POST", f"/api/v1/clients/{EXPECTED_CLIENT_ID}/assets", payload=payload)
    if not isinstance(data, dict):
        raise RuntimeError("Asset-Erstellungsantwort ist kein Objekt; vor Retry Bestand prüfen")
    return {
        "created": True,
        "client_id": EXPECTED_CLIENT_ID,
        "id": data.get("id"),
        "title": data.get("title"),
        "category_id": data.get("category_id"),
        "type_id": data.get("type_id"),
        "status_id": data.get("status_id"),
    }
