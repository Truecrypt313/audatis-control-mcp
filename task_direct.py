
    
  
"""Direct task creation for audatis MANAGER via MCP, without manual approval.

Copy next to server.py and register with: mcp.tool()(create_task)
The write credential is loaded locally from ~/.config/audatis-mcp/write_token.
No automatic retries are performed, to avoid duplicate task creation.
"""
from __future__ import annotations

import os
import stat
from datetime import date
from pathlib import Path

import httpx

from audatis_api import _origin

EXPECTED_CLIENT_ID = int(os.environ.get("AUDATIS_ALLOWED_CLIENT_ID", "0"))
WRITE_TOKEN_FILE = Path.home() / ".config" / "audatis-mcp" / "write_token"
PRIORITIES = frozenset({"none", "low", "normal", "high", "critical"})


def _write_token() -> str:
    if WRITE_TOKEN_FILE.is_symlink():
        raise RuntimeError("Schreib-Token-Datei darf kein Symlink sein")
    try:
        mode = WRITE_TOKEN_FILE.stat().st_mode
        if stat.S_IMODE(mode) & 0o077:
            raise RuntimeError("Schreib-Token-Datei: bitte chmod 600 setzen")
        token = WRITE_TOKEN_FILE.read_text(encoding="utf-8").strip()
    except FileNotFoundError as exc:
        raise RuntimeError(
            "Schreib-Token fehlt: ~/.config/audatis-mcp/write_token einrichten"
        ) from exc
    if not token:
        raise RuntimeError("Schreib-Token-Datei ist leer")
    return token


def create_task(
    subject: str,
    description: str = "",
    priority: str = "normal",
    due_date: str = "",
) -> dict:
    """Erstellt eine audatis-Aufgabe SOFORT, ohne weitere Freigabe. Nur für explizit gewünschte Aufgaben verwenden.

    Priorität: none/low/normal/high/critical. due_date: YYYY-MM-DD (optional).
    """
    if not isinstance(subject, str) or not 1 <= len(subject.strip()) <= 255:
        raise ValueError("subject muss 1 bis 255 Zeichen haben")
    if not isinstance(description, str) or len(description) > 5000:
        raise ValueError("description muss Text mit maximal 5000 Zeichen sein")
    if priority not in PRIORITIES:
        raise ValueError("priority: none, low, normal, high oder critical")
    if not isinstance(due_date, str):
        raise ValueError("due_date muss Text im Format YYYY-MM-DD sein")
    payload = {
        "subject": subject.strip(),
        "description": description,
        "type": "task",
        "status": "open",
        "priority": priority,
    }
    if due_date:
        try:
            parsed = date.fromisoformat(due_date)
        except ValueError as exc:
            raise ValueError("due_date muss YYYY-MM-DD sein") from exc
        if parsed.isoformat() != due_date:
            raise ValueError("due_date muss YYYY-MM-DD sein")
        payload["due_date"] = due_date

    if os.getenv("AUDATIS_CLIENT_ID") != str(EXPECTED_CLIENT_ID):
        raise RuntimeError("MCP ist nicht für den erwarteten Testmandanten konfiguriert")
    base_url = _origin(os.environ.get("AUDATIS_BASE_URL", ""))
    token = _write_token()

    try:
        with httpx.Client(
            base_url=base_url, timeout=20.0,
            follow_redirects=False, trust_env=False,
        ) as client:
            response = client.post(
                f"/api/v1/clients/{EXPECTED_CLIENT_ID}/tasks",
                headers={
                    "Authorization": f"Bearer {token}",
                    "Accept": "application/json",
                },
                json=payload,
            )
    except httpx.RequestError as exc:
        raise RuntimeError(
            "Netzwerkfehler: Vor einem erneuten Aufruf die Aufgabenliste prüfen, "
            "da eine Erstellung möglicherweise bereits erfolgt ist"
        ) from exc

    if response.status_code != 201:
        raise RuntimeError(
            f"audatis HTTP {response.status_code}: Aufgabe nicht als erstellt bestätigt "
            "(Token-Scope, Berechtigungen und Pflichtfelder prüfen)"
        )
    try:
        item = response.json()["data"]
    except (ValueError, KeyError, TypeError) as exc:
        raise RuntimeError(
            "HTTP 201 erhalten, aber Antwortformat unerwartet; vor Wiederholung "
            "die Aufgabenliste prüfen"
        ) from exc
    if not isinstance(item, dict):
        raise RuntimeError("HTTP 201 erhalten; Antwortformat unerwartet")
    return {
        "created": True,
        "client_id": EXPECTED_CLIENT_ID,
        "id": item.get("id"),
        "subject": item.get("subject"),
        "status": item.get("status"),
        "priority": item.get("priority"),
        "due_date": item.get("due_date"),
    }

