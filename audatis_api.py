"""Read-only audatis MANAGER REST API adapter (OpenAPI 1.3.0).

No write methods, dynamic arbitrary paths or redirection are exposed here.
"""
from __future__ import annotations

from pathlib import Path
from dotenv import load_dotenv

import os
from urllib.parse import urlsplit

import httpx


class ConfigurationError(RuntimeError):
    """Missing or unsafe environment setting."""


def _origin(raw_url: str) -> str:
    """Use only a user-configured HTTPS origin, never a URL chosen by an LLM."""
    parsed = urlsplit(raw_url.strip())
    if (
        parsed.scheme != "https"
        or not parsed.hostname
        or parsed.username
        or parsed.password
        or parsed.path not in ("", "/")
        or parsed.query
        or parsed.fragment
    ):
        raise ConfigurationError(
            "AUDATIS_BASE_URL muss eine HTTPS-Origin sein, z. B. "
            "https://dein-audatis-host.example (ohne /api-Pfad)."
        )
    return raw_url.strip().rstrip("/")


class AudatisAPI:
    def __init__(
        self,
        base_url: str,
        token: str,
        client_id: int | None = None,
        *,
        transport: httpx.BaseTransport | None = None,
    ) -> None:
        self.base_url = _origin(base_url)
        if not token.strip():
            raise ConfigurationError("AUDATIS_API_TOKEN fehlt")
        if client_id is not None and client_id <= 0:
            raise ConfigurationError("AUDATIS_CLIENT_ID muss eine positive Zahl sein")
        self._token = token.strip()
        self.client_id = client_id
        self._transport = transport

    @classmethod
    def from_env(cls, *, require_client: bool = True) -> "AudatisAPI":
        load_dotenv(Path(__file__).with_name(".env"), override=False)
        raw_id = os.environ.get("AUDATIS_CLIENT_ID", "")
        try:
            client_id = int(raw_id) if raw_id else None
        except ValueError as exc:
            raise ConfigurationError("AUDATIS_CLIENT_ID muss numerisch sein") from exc
        if require_client and client_id is None:
            raise ConfigurationError("AUDATIS_CLIENT_ID fehlt")
        return cls(
            base_url=os.environ.get("AUDATIS_BASE_URL", ""),
            token=os.environ.get("AUDATIS_API_TOKEN", ""),
            client_id=client_id,
        )

    def _get(self, path: str, params: dict[str, str | int | None] | None = None) -> dict:
        """Only caller-authored fixed paths; never follow redirects with bearer headers."""
        headers = {
            "Authorization": f"Bearer {self._token}",
            "Accept": "application/json",
        }
        try:
            with httpx.Client(
                base_url=self.base_url,
                timeout=15.0,
                follow_redirects=False,
                transport=self._transport,
                trust_env=False,  # do not route tokens via untrusted proxy env vars
            ) as client:
                response = client.get(path, headers=headers, params=params)
        except httpx.RequestError as exc:
            raise RuntimeError("Netzwerkfehler bei audatisManager (HTTPS/Host prüfen)") from exc
        if response.status_code != 200:
            hints = {
                301: "Weiterleitung erhalten: AUDATIS_BASE_URL prüfen",
                302: "Weiterleitung erhalten: eventuell Loginseite statt API-Host",
                401: "Unauthorized: Token prüfen oder neu ausstellen",
                403: "Forbidden: API-/Mandanten-/Benutzerrechte oder Token-Scope prüfen",
                404: "Nicht gefunden: Host, Mandant oder Ressourcen-ID prüfen",
                422: "Validierungsfehler: Filter prüfen",
            }
            message = hints.get(response.status_code, "API-Anfrage fehlgeschlagen")
            raise RuntimeError(f"audatis HTTP {response.status_code}: {message}")
        try:
            result = response.json()
        except ValueError as exc:
            raise RuntimeError("API antwortet nicht mit JSON (Host prüfen)") from exc
        if not isinstance(result, dict):
            raise RuntimeError("Unerwartetes API-Antwortformat")
        return result

    def accessible_clients(self, page: int = 1, per_page: int = 10) -> dict:
        return self._get("/api/v1/clients", {"page": page, "per_page": per_page})

    def tenant_get(self, resource: str, *, page: int = 1, per_page: int = 10, **filters: str) -> dict:
        """Resource and filters are explicitly allowlisted, never raw URLs."""
        allowed = {
            "assets": set(),
            "risks": {"status", "risk_type"},
            "tasks": {"status", "priority"},
            "incidents": {"status", "severity", "search"},
        }
        if resource not in allowed or set(filters) - allowed[resource]:
            raise ValueError("Ressource/Filter nicht freigegeben")
        if self.client_id is None:
            raise ConfigurationError("AUDATIS_CLIENT_ID fehlt")
        if not 1 <= page <= 10000 or not 1 <= per_page <= 100:
            raise ValueError("page muss 1..10000, per_page 1..100 sein")
        params: dict[str, str | int] = {"page": page, "per_page": per_page}
        params.update({k: v for k, v in filters.items() if v})
        return self._get(f"/api/v1/clients/{self.client_id}/{resource}", params)


def summarize_list(response: dict, fields: tuple[str, ...]) -> dict:
    """Limit model exposure to needed attributes; keep pagination metadata."""
    raw_data = response.get("data", [])
    if not isinstance(raw_data, list):
        raise RuntimeError("Unerwartete Listen-Antwort")
    return {
        "data": [{key: item.get(key) for key in fields} for item in raw_data if isinstance(item, dict)],
        "meta": response.get("meta", {}),
    }
