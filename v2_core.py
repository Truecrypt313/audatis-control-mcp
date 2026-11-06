"""V2 API transport and strict OpenAPI request validation.

Additive extension: does not modify the user's existing audatis_api.py or tools.
All paths are authored here, pinned to EXPECTED_CLIENT_ID and never model-supplied.
"""
from __future__ import annotations

import json
import os
import re
from copy import deepcopy
from pathlib import Path
from uuid import UUID

import httpx
from jsonschema import Draft202012Validator, FormatChecker
from audatis_api import AudatisAPI, _origin
from task_direct import EXPECTED_CLIENT_ID, _write_token

BASE = f"/api/v1/clients/{EXPECTED_CLIENT_ID}"
READ_RESOURCES = frozenset({
    "assets", "tasks", "information-values", "business-processes", "measures",
    "risks", "incidents", "reports",
})
WRITE_RESOURCES = frozenset({
    "assets", "tasks", "information-values", "business-processes", "measures",
})
LINK_KINDS = {
    "assets": "asset_id",
    "measures": "measure_id",
    "business-processes": "business_process_id",
    "information-values": "information_value_id",
}
LOOKUPS = {
    "asset_categories": "assets/categories",
    "asset_statuses": "assets/statuses",
    "asset_protection_levels": "assets/protection-levels",
    "asset_criticality_levels": "assets/criticality-levels",
    "asset_relationship_types": "assets/relationship-types",
    "information_classifications": "information-values/classifications",
    "information_protection_needs": "/api/v1/information-values/protection-needs",
    "business_process_statuses": "/api/v1/business-processes/statuses",
    "business_process_criticality_levels": "business-processes/criticality-levels",
    "measure_types": "/api/v1/measures/types",
    "measure_implementation_statuses": "/api/v1/measures/implementation-statuses",
    "task_statuses": "/api/v1/tasks/statuses",
    "task_priorities": "/api/v1/tasks/priorities",
    "incident_statuses": "/api/v1/incidents/statuses",
}

# A carefully selected subset of OpenAPI request fields, not an unrestricted JSON write proxy.
# On partial update of nested objects we deliberately forbid fields with replacement ambiguity.
_FIELDS = {
    "assets": {
        "create": "title category_id type_id asset_owner_user_id additional_responsible_user_ids tag_ids",
        "update": "title description type_id status_id asset_owner_user_id additional_responsible_user_ids tag_ids is_group parent_id is_shared",
    },
    "tasks": {
        "create": "subject description type status priority progress assigned_to_user_id start_date due_date",
        "update": "subject description type status priority progress assigned_to_user_id start_date due_date",
    },
    "information-values": {
        "create": "title description asset_owner_user_id has_personal_reference has_art9_data protection_needs classification_id text_module_id additional_responsible_ids tag_ids next_review_at has_mandate_approval",
        "update": "title description asset_owner_user_id has_personal_reference has_art9_data classification_id text_module_id additional_responsible_ids tag_ids next_review_at has_mandate_approval",
    },
    "business-processes": {
        "create": "title description process_owner_id organisation_id parent_id protection_need protection_need_justification criticality process_type_id tag_ids status process resources key_figures risk_description next_review_at has_mandate_approval",
        "update": "title description process_owner_id organisation_id parent_id protection_need protection_need_justification criticality process_type_id tag_ids status resources key_figures risk_description next_review_at has_mandate_approval",
    },
    "measures": {
        "create": "title description type is_confidentiality_goal is_integrity_goal is_availability_goal implementation_status is_effectiveness_active next_review_at responsible_user_id is_released tag_ids",
        "update": "title description type is_confidentiality_goal is_integrity_goal is_availability_goal implementation_status is_effectiveness_active next_review_at responsible_user_id is_released tag_ids",
    },
}
ALLOWED_FIELDS = {resource: {mode: frozenset(s.split()) for mode, s in modes.items()}
                  for resource, modes in _FIELDS.items()}
REQUIRED_IDENTITY = {"tasks": "subject"}  # All other writable resources use title.


def uuid_id(value: str, label: str = "ID") -> str:
    if not isinstance(value, str):
        raise ValueError(f"{label}: UUID erwartet")
    try:
        return str(UUID(value))
    except ValueError as exc:
        raise ValueError(f"{label}: ungültige UUID") from exc


def resource_id(resource: str, value: str | int) -> str:
    """Validate path ID according to each OpenAPI endpoint, not one global UUID rule."""
    if resource not in READ_RESOURCES:
        raise ValueError("Unbekannte Ressource")
    if resource == "reports":
        if type(value) not in (str, int) or not re.fullmatch(r"[1-9][0-9]{0,9}", str(value)):
            raise ValueError("Berichts-ID muss eine positive dezimale Zahl sein")
        return str(value)
    if resource == "business-processes":
        if not isinstance(value, str) or not re.fullmatch(r"[a-zA-Z0-9_-]{1,120}", value):
            raise ValueError("Ungültige Geschäftsprozess-ID")
        if value in {"tags", "process-types", "criticality-levels"}:
            raise ValueError("Reservierte Geschäftsprozess-ID")
        return value
    return uuid_id(value)


def parse_json(value: str, *, expect: type = dict):
    if not isinstance(value, str) or len(value) > 30000:
        raise ValueError("JSON muss ein String mit höchstens 30.000 Zeichen sein")
    try:
        result = json.loads(value)
    except json.JSONDecodeError as exc:
        raise ValueError("Ungültiges JSON") from exc
    if type(result) is not expect:
        raise ValueError("JSON muss ein " + ("Objekt" if expect is dict else "Array") + " sein")
    return result


def _load_contract():
    with Path(__file__).with_name("v2_contract.json").open(encoding="utf-8") as f:
        return json.load(f)


_CONTRACT = _load_contract()


def validate_payload(resource: str, mode: str, payload: dict, *, partial: bool = False) -> dict:
    """Fail closed for unsupported fields, types, date/UUID formats and nested keys.

    `partial=True` is only for a change set. Required identity is fetched separately
    from the live record before PUT and then the complete request is revalidated.
    """
    if resource not in WRITE_RESOURCES or mode not in ("create", "update"):
        raise ValueError("Ressource bzw. Operation nicht schreibbar")
    if type(payload) is not dict or not payload:
        raise ValueError("Nichtleeres JSON-Objekt erwartet")
    extras = set(payload) - ALLOWED_FIELDS[resource][mode]
    if extras:
        raise ValueError(f"Felder für {resource}/{mode} nicht freigegeben: {', '.join(sorted(extras))}")
    schema = deepcopy(_CONTRACT["requests"][resource][mode])
    if partial:
        schema.pop("required", None)
    wrapper = {**schema, "$defs": _CONTRACT["definitions"]}
    validator = Draft202012Validator(wrapper, format_checker=FormatChecker())
    errors = sorted(validator.iter_errors(payload), key=lambda e: (list(map(str, e.path)), e.message))
    if errors:
        e = errors[0]
        location = ".".join(map(str, e.path)) or "Objekt"
        raise ValueError(f"Ungültiges Feld {location}: {e.message}")
    # API IDs in JSON bodies do not all declare `format: uuid` in OpenAPI.
    # For the asset fields known to be UUID references, reject malformed values locally.
    if resource == "assets":
        for field in ("category_id", "type_id", "status_id", "parent_id"):
            if field in payload and payload[field] is not None:
                uuid_id(payload[field], field)
    # Fail-safe: nested protection objects on CREATE must specify all three dimensions.
    if resource == "information-values" and mode == "create" and "protection_needs" in payload:
        needs = payload["protection_needs"]
        if type(needs) is not dict or set(needs) != {"confidentiality", "integrity", "availability"}:
            raise ValueError("protection_needs: C, I und A vollständig angeben")
        for dimension, entry in needs.items():
            if type(entry) is not dict or "level" not in entry:
                raise ValueError(f"protection_needs.{dimension}.level fehlt")
    return dict(payload)


class V2API:
    """HTTP client testable via httpx.MockTransport. No redirects, proxies or retries."""
    def __init__(self, base_url: str, read_token: str, *, client_id: int = EXPECTED_CLIENT_ID,
                 write_token: str | None = None, transport: httpx.BaseTransport | None = None):
        if type(client_id) is not int or client_id != EXPECTED_CLIENT_ID:
            raise ValueError("Nur der konfigurierte Testmandant ist erlaubt")
        if not isinstance(read_token, str) or not read_token.strip():
            raise ValueError("Lesetoken fehlt")
        self.origin = _origin(base_url)
        self.read_token = read_token.strip()
        self._write_token_override = write_token
        self._transport = transport

    @classmethod
    def from_env(cls):
        old = AudatisAPI.from_env()  # loads .env, validates token, host and client
        if old.client_id != EXPECTED_CLIENT_ID or os.getenv("AUDATIS_CLIENT_ID") != str(EXPECTED_CLIENT_ID):
            raise RuntimeError("Konfigurierter Mandant entspricht nicht dem Testmandanten")
        return cls(old.base_url, old._token, client_id=old.client_id)

    def _call(self, method: str, path: str, *, params: dict | None = None,
              payload: dict | None = None, statuses: tuple[int, ...] = (200,)) -> dict:
        if method not in ("GET", "POST", "PUT"):
            raise ValueError("HTTP-Methode gesperrt")
        token = self.read_token if method == "GET" else (self._write_token_override or _write_token())
        headers = {"Authorization": f"Bearer {token}", "Accept": "application/json"}
        try:
            with httpx.Client(base_url=self.origin, timeout=20.0, follow_redirects=False,
                              transport=self._transport, trust_env=False) as client:
                r = client.request(method, path, params=params, json=payload, headers=headers)
        except httpx.RequestError as exc:
            raise RuntimeError("Netzwerkfehler: Schreibstatus vor einem erneuten Versuch prüfen; kein Auto-Retry") from exc
        if r.status_code not in statuses:
            hints = {401: "Token prüfen", 403: "Berechtigung prüfen", 404: "ID/Ressource nicht gefunden",
                     409: "Konflikt", 422: "API-Validierung fehlgeschlagen"}
            raise RuntimeError(f"audatis HTTP {r.status_code}: {hints.get(r.status_code, 'Anfrage fehlgeschlagen')}")
        try:
            body = r.json()
        except ValueError as exc:
            raise RuntimeError("API antwortete nicht mit JSON; Zustand prüfen") from exc
        if not isinstance(body, dict) or "data" not in body:
            raise RuntimeError("Unerwartete API-Antwort; vor Schreibwiederholung Zustand prüfen")
        return body

    def records(self, resource: str, *, page: int = 1, per_page: int = 50) -> dict:
        if resource not in READ_RESOURCES:
            raise ValueError("Ressource nicht freigegeben")
        if type(page) is not int or not 1 <= page <= 10000 or type(per_page) is not int or not 1 <= per_page <= 200:
            raise ValueError("page 1..10000, per_page 1..200")
        return self._call("GET", f"{BASE}/{resource}", params={"page": page, "per_page": per_page})

    def record(self, resource: str, record_id: str) -> dict:
        if resource not in READ_RESOURCES:
            raise ValueError("Ressource nicht freigegeben")
        return self._call("GET", f"{BASE}/{resource}/{resource_id(resource, record_id)}")

    def create(self, resource: str, payload: dict) -> dict:
        payload = validate_payload(resource, "create", payload)
        return self._call("POST", f"{BASE}/{resource}", payload=payload, statuses=(201,))

    def update(self, resource: str, record_id: str, changes: dict, *, current: dict | None = None) -> dict:
        record_id = resource_id(resource, record_id)
        changes = validate_payload(resource, "update", changes, partial=True)
        if current is None:
            current = self.record(resource, record_id)["data"]
        if not isinstance(current, dict):
            raise RuntimeError("GET-Vorabfrage lieferte kein Objekt")
        identity = REQUIRED_IDENTITY.get(resource, "title")
        existing_identity = current.get(identity)
        if not isinstance(existing_identity, str) or not existing_identity.strip():
            raise RuntimeError(f"Aktueller {identity}-Wert fehlt; Update abgebrochen")
        if "id" in current and str(current["id"]).lower() != record_id.lower():
            raise RuntimeError("Antwort-ID passt nicht zur Ziel-ID")
        modified = {key: value for key, value in changes.items() if current.get(key) != value}
        if not modified:
            return {"updated": False, "data": current}
        payload = {identity: existing_identity, **modified}
        validate_payload(resource, "update", payload)
        result = self._call("PUT", f"{BASE}/{resource}/{record_id}", payload=payload)
        return {"updated": True, **result}

    def lookup(self, name: str) -> dict:
        if name not in LOOKUPS:
            raise ValueError("Unbekannter Lookup")
        path = LOOKUPS[name]
        if not path.startswith("/api/v1/"):
            path = f"{BASE}/{path}"
        return self._call("GET", path)

    def incident_links(self, incident_id: str, kind: str, *, target_id: str | None = None) -> dict:
        if kind not in LINK_KINDS:
            raise ValueError("Unbekannter Verknüpfungstyp")
        path = f"{BASE}/incidents/{uuid_id(incident_id, 'incident_id')}/{kind}"
        if target_id is None:
            return self._call("GET", path)
        target_id = uuid_id(target_id, "target_id")
        return self._call("POST", path, payload={LINK_KINDS[kind]: target_id}, statuses=(200, 201))

    def audit_log(self, *, page: int, per_page: int, entity_type: str = "", action: str = "") -> dict:
        if type(page) is not int or not 1 <= page <= 10000 or type(per_page) is not int or not 1 <= per_page <= 200:
            raise ValueError("Ungültige Pagination")
        if len(entity_type) > 80 or len(action) > 80:
            raise ValueError("Filter zu lang")
        params = {"page": page, "per_page": per_page}
        if entity_type:
            params["entity_type"] = entity_type
        if action:
            params["action"] = action
        return self._call("GET", f"{BASE}/audit-log", params=params)


def collect_all(api: V2API, resource: str, *, max_pages: int = 5, per_page: int = 100):
    """Bounded full traversal; returns (entries, is_complete).

    Never silently interpret a partial inventory as complete.
    """
    if type(max_pages) is not int or not 1 <= max_pages <= 10:
        raise ValueError("max_pages muss 1..10 sein")
    out = []
    for page in range(1, max_pages + 1):
        body = api.records(resource, page=page, per_page=per_page)
        chunk = body["data"]
        if not isinstance(chunk, list):
            raise RuntimeError("API-Liste ist kein Array")
        out.extend(chunk)
        meta = body.get("meta") or {}
        if len(chunk) < per_page:
            return out, True
        total_pages = meta.get("total_pages")
        if type(total_pages) is int and page >= total_pages:
            return out, True
        if type(meta.get("total")) is int and len(out) >= meta["total"]:
            return out, True
    return out, False
