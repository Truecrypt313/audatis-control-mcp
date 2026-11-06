"""MCP tools for listing audatis users and updating asset owner / text fields.

Requires the existing asset_management.py and task_direct.py modules.
OpenAPI 1.3.0:
  GET /api/v1/clients/{mid}/users
  GET/PUT /api/v1/clients/{mid}/assets/{pid}

Only one fixed test client is supported; no delete or generic HTTP access.
The write token is read locally through the existing asset_management._settings.
"""
from __future__ import annotations

import httpx

from asset_management import _settings, _uuid, get_asset
from task_direct import EXPECTED_CLIENT_ID


_FIELDS = ("id", "title", "description", "category_id", "type_id", "asset_owner_user_id", "updated_at")


def _api_call(method: str, path: str, *, params: dict | None = None, payload: dict | None = None) -> dict:
    """Send fixed author-controlled requests, without redirects, proxies or retries."""
    if method not in ("GET", "PUT"):
        raise ValueError("Nur GET/PUT erlaubt")
    origin, token = _settings()
    try:
        with httpx.Client(base_url=origin, timeout=20, follow_redirects=False, trust_env=False) as client:
            response = client.request(
                method,
                path,
                params=params,
                json=payload,
                headers={"Authorization": f"Bearer {token}", "Accept": "application/json"},
            )
    except httpx.RequestError as exc:
        raise RuntimeError("Netzwerkfehler: Bei Änderungen Assetzustand vor erneutem Versuch prüfen") from exc
    if response.status_code != 200:
        reason = {
            401: "API-Token ungültig oder abgelaufen",
            403: "Token- oder Modulberechtigung fehlt (Benutzerverwaltung / Assetmanagement)",
            404: "Mandant oder Ressource nicht gefunden",
            422: "API-Validierung fehlgeschlagen (Benutzer-ID oder Felddaten prüfen)",
        }.get(response.status_code, "API-Aufruf fehlgeschlagen")
        raise RuntimeError(f"audatis HTTP {response.status_code}: {reason}")
    try:
        result = response.json()
    except ValueError as exc:
        raise RuntimeError("audatis antwortete nicht mit gültigem JSON") from exc
    if not isinstance(result, dict) or "data" not in result:
        raise RuntimeError("Unerwartetes API-Antwortformat")
    return result


def list_users(page: int = 1, per_page: int = 100) -> dict:
    """Listet Benutzer des Testmandanten (ID und Name). Nur lesender API-Zugriff.

    Für diesen Endpunkt benötigt der Token-Benutzer 'Benutzerverwaltung' (Lesen).
    """
    if isinstance(page, bool) or not isinstance(page, int) or not 1 <= page <= 10000:
        raise ValueError("page muss eine positive ganze Zahl bis 10000 sein")
    if isinstance(per_page, bool) or not isinstance(per_page, int) or not 1 <= per_page <= 200:
        raise ValueError("per_page muss zwischen 1 und 200 liegen")
    response = _api_call(
        "GET", f"/api/v1/clients/{EXPECTED_CLIENT_ID}/users",
        params={"page": page, "per_page": per_page},
    )
    data = response["data"]
    if not isinstance(data, list):
        raise RuntimeError("Unerwartete Benutzerliste")
    return {
        "client_id": EXPECTED_CLIENT_ID,
        "data": [{"id": u.get("id"), "name": u.get("name")} for u in data if isinstance(u, dict)],
        "meta": response.get("meta", {}),
    }


def update_asset(
    asset_id: str,
    asset_owner_user_id: int = -1,
    title: str = "",
    description: str = "",
    clear_description: bool = False,
) -> dict:
    """Ändert ein Asset SOFORT im Testmandanten (ohne separate Freigabe).

    asset_owner_user_id: -1=unverändert, 0=Owner entfernen, >0=Benutzer-ID setzen.
    title/description: leere Zeichenfolge = unverändert.
    clear_description=True entfernt die Beschreibung; nicht zusammen mit description verwenden.

    Die audatis-API verlangt beim PUT das Feld 'title', auch bei einer Owner-Änderung.
    Deshalb wird vor dem Update das Asset ausgelesen und der bisherige Titel beibehalten.
    """
    asset_id = _uuid(asset_id, "asset_id")
    if isinstance(asset_owner_user_id, bool) or not isinstance(asset_owner_user_id, int) or asset_owner_user_id < -1:
        raise ValueError("asset_owner_user_id: -1, 0 oder positive numerische Benutzer-ID")
    if not isinstance(title, str) or not isinstance(description, str):
        raise ValueError("title und description müssen Texte sein")
    if clear_description and description:
        raise ValueError("description und clear_description schließen sich aus")
    if title and not 1 <= len(title.strip()) <= 255:
        raise ValueError("title muss 1 bis 255 Zeichen haben")
    updates: dict = {}
    if asset_owner_user_id != -1:
        updates["asset_owner_user_id"] = None if asset_owner_user_id == 0 else asset_owner_user_id
    if title:
        updates["title"] = title.strip()
    if description:
        updates["description"] = description
    if clear_description:
        updates["description"] = None
    if not updates:
        raise ValueError("Keine Änderungen angegeben")

    before = get_asset(asset_id)["asset"]
    current_title = before.get("title")
    if not isinstance(current_title, str) or not current_title:
        raise RuntimeError("Vorhandener Asset-Titel ist ungültig, Update abgebrochen")
    changed = {field: value for field, value in updates.items() if before.get(field) != value}
    if not changed:
        return {"updated": False, "client_id": EXPECTED_CLIENT_ID, "reason": "Bereits identische Werte",
                "asset": {key: before.get(key) for key in _FIELDS}}

    # PUT uses partial semantics, but 'title' is mandatory even for owner-only changes.
    payload = {"title": changed.get("title", current_title), **changed}
    result = _api_call("PUT", f"/api/v1/clients/{EXPECTED_CLIENT_ID}/assets/{asset_id}", payload=payload)["data"]
    if not isinstance(result, dict):
        raise RuntimeError("Unerwartete Antwort nach Asset-Update; Zustand vor erneutem Versuch prüfen")
    return {
        "updated": True,
        "client_id": EXPECTED_CLIENT_ID,
        "changed_fields": sorted(changed),
        "asset": {key: result.get(key) for key in _FIELDS},
    }
