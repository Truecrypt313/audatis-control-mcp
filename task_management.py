"""audatis MANAGER MCP tools: read a single task and modify selected task fields.

OpenAPI 1.3.0: GET/PUT /api/v1/clients/{mid}/tasks/{auid}

Copy next to server.py and task_direct.py, then register:
    from task_management import get_task, update_task
    mcp.tool()(get_task)
    mcp.tool()(update_task)

Reuses the local write token stored by task_direct.py. Never puts token in tool
arguments or results. This module exposes no DELETE operation.
"""
from __future__ import annotations

import os
from datetime import date
from uuid import UUID

import httpx

from audatis_api import _origin
from task_direct import EXPECTED_CLIENT_ID, _write_token

TASK_PRIORITIES = frozenset({"none", "low", "normal", "high", "critical"})
TASK_STATUSES = frozenset({
    "open", "in_progress", "waiting", "completed", "cancelled",
    "not_relevant", "not_feasible", "planned",
})
_VISIBLE = (
    "id", "number", "subject", "description", "type", "status",
    "priority", "progress", "assigned_to_user_id", "start_date",
    "due_date", "is_overdue", "created_at", "updated_at",
)


def _task_id(raw: str) -> str:
    """Keep task paths confined to a single UUID, never an LLM-supplied path."""
    try:
        return str(UUID(raw))
    except (ValueError, AttributeError, TypeError) as exc:
        raise ValueError("task_id muss eine gültige UUID sein") from exc


def _settings() -> tuple[str, str]:
    if os.getenv("AUDATIS_CLIENT_ID") != str(EXPECTED_CLIENT_ID):
        raise RuntimeError("MCP ist nicht für den erwarteten Testmandanten konfiguriert")
    origin = _origin(os.environ.get("AUDATIS_BASE_URL", ""))
    token = _write_token()
    return origin, token


def _call(method: str, task_id: str, payload: dict | None = None) -> dict:
    origin, token = _settings()
    path = f"/api/v1/clients/{EXPECTED_CLIENT_ID}/tasks/{task_id}"
    headers = {"Authorization": f"Bearer {token}", "Accept": "application/json"}
    try:
        with httpx.Client(
            base_url=origin,
            timeout=20.0,
            follow_redirects=False,
            trust_env=False,
        ) as client:
            response = client.request(method, path, headers=headers, json=payload)
    except httpx.RequestError as exc:
        # No retry: a PUT might already have been applied despite a network error.
        raise RuntimeError(
            "Netzwerkfehler; Zustand der Aufgabe vor erneutem Aufruf prüfen"
        ) from exc

    if response.status_code != 200:
        hints = {
            401: "Token ungültig oder abgelaufen",
            403: "Berechtigung/Token-Scope/Mandant prüfen",
            404: "Aufgabe nicht vorhanden oder nicht zugänglich",
            422: "Feldwert ungültig; API-Validierung prüfen",
        }
        raise RuntimeError(
            f"audatis HTTP {response.status_code}: "
            f"{hints.get(response.status_code, 'API-Aufruf fehlgeschlagen')}"
        )
    try:
        data = response.json()["data"]
    except (ValueError, KeyError, TypeError) as exc:
        raise RuntimeError("Unerwartete API-Antwort; vor Wiederholung Zustand prüfen") from exc
    if not isinstance(data, dict):
        raise RuntimeError("Unerwartete API-Antwortstruktur")
    return data


def _visible(task: dict) -> dict:
    return {field: task.get(field) for field in _VISIBLE}


def get_task(task_id: str) -> dict:
    """Liest eine einzelne audatis-Aufgabe per UUID. Ändert keine Daten.

    Nutzt den lokal gespeicherten Token, der bereits für create_task verwendet wird.
    """
    task_id = _task_id(task_id)
    task = _call("GET", task_id)
    return {"client_id": EXPECTED_CLIENT_ID, "task": _visible(task)}


def update_task(
    task_id: str,
    subject: str = "",
    description: str = "",
    priority: str = "",
    status: str = "",
    due_date: str = "",
    clear_due_date: bool = False,
    assigned_to_user_id: int = -1,
) -> dict:
    """Ändert eine audatis-Aufgabe SOFORT (ohne separate Freigabe).

    Nur angegebene Felder werden geändert:
      - subject/description: leerer String bedeutet *nicht ändern*;
      - priority: none/low/normal/high/critical;
      - status: open/in_progress/waiting/completed/cancelled/not_relevant/
        not_feasible/planned;
      - due_date: YYYY-MM-DD, oder clear_due_date=True um Datum zu entfernen;
      - assigned_to_user_id: -1=unverändert, 0=Zuweisung entfernen,
        positive Zahl=Benutzer-ID setzen.

    Wichtig: Die API verlangt subject auch beim PUT. Deshalb wird der aktuelle
    Betreff zuerst per GET geladen und bei Teiländerungen beibehalten.
    Kein DELETE, kein automatisches Wiederholen bei Fehlern.
    """
    task_id = _task_id(task_id)
    updates = {}

    if subject:
        if not isinstance(subject, str) or not 1 <= len(subject.strip()) <= 255:
            raise ValueError("subject muss 1 bis 255 Zeichen haben")
        updates["subject"] = subject.strip()
    if description:
        if not isinstance(description, str) or len(description) > 5000:
            raise ValueError("description muss Text mit max. 5000 Zeichen sein")
        updates["description"] = description
    if priority:
        if priority not in TASK_PRIORITIES:
            raise ValueError("priority: none, low, normal, high oder critical")
        updates["priority"] = priority
    if status:
        if status not in TASK_STATUSES:
            raise ValueError("status ungültig; siehe TaskUpdateRequest")
        updates["status"] = status
    if due_date:
        try:
            parsed = date.fromisoformat(due_date)
        except (ValueError, TypeError) as exc:
            raise ValueError("due_date muss YYYY-MM-DD sein") from exc
        if parsed.isoformat() != due_date:
            raise ValueError("due_date muss YYYY-MM-DD sein")
        updates["due_date"] = due_date
    if clear_due_date:
        if due_date:
            raise ValueError("due_date und clear_due_date schließen sich aus")
        updates["due_date"] = None
    if isinstance(assigned_to_user_id, bool) or not isinstance(assigned_to_user_id, int):
        raise ValueError("assigned_to_user_id muss ganzzahlig sein")
    if assigned_to_user_id < -1:
        raise ValueError("assigned_to_user_id: -1, 0 oder positive Benutzer-ID")
    if assigned_to_user_id != -1:
        updates["assigned_to_user_id"] = (
            None if assigned_to_user_id == 0 else assigned_to_user_id
        )

    if not updates:
        raise ValueError("Keine Änderungen angegeben")

    current = _call("GET", task_id)
    current_subject = current.get("subject")
    if not isinstance(current_subject, str) or not current_subject:
        raise RuntimeError("Aufgabe hat keinen gültigen Betreff; Update abgebrochen")

    changed = {name: value for name, value in updates.items() if current.get(name) != value}
    if not changed:
        return {"updated": False, "reason": "Bereits identische Werte", "task": _visible(current)}

    payload = {"subject": changed.get("subject", current_subject), **changed}
    result = _call("PUT", task_id, payload)
    return {
        "updated": True,
        "client_id": EXPECTED_CLIENT_ID,
        "changed_fields": sorted(changed),
        "task": _visible(result),
    }
