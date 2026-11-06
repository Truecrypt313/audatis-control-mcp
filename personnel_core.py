"""Personal/Organisations adapter. Uses the existing V2API HTTP and token safety.

Endpoints and allowed field schemas are derived from audatis OpenAPI 1.3.0.
No API-URL parameters, redirects, retries, deletion, user creation or mail sending.
"""
from __future__ import annotations

import json
from pathlib import Path

from jsonschema import Draft202012Validator, FormatChecker

from v2_core import BASE, V2API, parse_json

CONTRACT = json.loads(Path(__file__).with_name("personnel_contract.json").read_text(encoding="utf-8"))
CREATE_FIELDS = frozenset(CONTRACT["create"]["properties"])
UPDATE_FIELDS = frozenset(CONTRACT["update"]["properties"])
MAX_BULK_PERSONS = 25  # API allows 500; consciously safer MCP batch cap.


def positive_id(value: int, name: str = "ID") -> int:
    if type(value) is not int or value < 1 or value > 2_147_483_647:
        raise ValueError(f"{name}: positive Ganzzahl erwartet")
    return value


def _validated(schema_name: str, data: dict, *, partial: bool = False) -> dict:
    if type(data) is not dict or not data:
        raise ValueError("Nichtleeres JSON-Objekt erwartet")
    schema = json.loads(json.dumps(CONTRACT[schema_name]))
    if partial:
        schema.pop("required", None)
    errors = sorted(Draft202012Validator(schema, format_checker=FormatChecker()).iter_errors(data),
                    key=lambda x: (list(map(str, x.path)), x.message))
    if errors:
        err = errors[0]
        path = ".".join(map(str, err.path)) or "Payload"
        raise ValueError(f"Ungültiges Feld {path}: {err.message}")
    # Invalid blank/whitespace-only names and email addresses are not useful.
    for name in ("first_name", "last_name", "email"):
        if name in data and not data[name].strip():
            raise ValueError(f"{name} darf nicht leer sein")
    return dict(data)


def validate_create(payload_json: str) -> dict:
    return _validated("create", parse_json(payload_json))


def validate_update(changes_json: str) -> dict:
    return _validated("update", parse_json(changes_json), partial=True)


def ids_json(value: str, name: str, *, allow_empty: bool = False, max_items: int = 25) -> list[int]:
    items = parse_json(value, expect=list)
    if (not items and not allow_empty) or len(items) > max_items:
        raise ValueError(f"{name}: {1 if not allow_empty else 0} bis {max_items} IDs erwartet")
    for value in items:
        positive_id(value, name)
    if len(set(items)) != len(items):
        raise ValueError(f"{name}: doppelte IDs nicht zulässig")
    return items


def _data(result: dict, *, list_expected: bool = False):
    data = result.get("data")
    if not isinstance(data, list if list_expected else dict):
        raise RuntimeError("Unerwartete API-Antwort; keinen Schreibvorgang wiederholen")
    return data


class PersonnelAPI(V2API):
    """Restricts all paths to the tenant configured by the original V2 client."""

    def organisations(self, *, page: int = 1, per_page: int = 50) -> dict:
        self.check_page(page, per_page)
        return self._call("GET", f"{BASE}/organisations", params={"page": page, "per_page": per_page})

    def organisation(self, org_id: int) -> dict:
        return self._call("GET", f"{BASE}/organisations/{positive_id(org_id, 'organisation_id')}")

    def persons(self, *, page: int = 1, per_page: int = 50, archived: str = "false",
                q: str = "", organisation_id: int = 0, email: str = "") -> dict:
        self.check_page(page, per_page)
        if archived not in ("false", "true", "all"):
            raise ValueError("archived muss false, true oder all sein")
        if not isinstance(q, str) or len(q) > 120 or not isinstance(email, str) or len(email) > 255:
            raise ValueError("Suchwert zu lang/ungültig")
        params = {"page": page, "per_page": per_page, "archived": archived}
        if q:
            params["q"] = q
        if email:
            params["email"] = email
        if organisation_id:
            params["organisation_id"] = positive_id(organisation_id, "organisation_id")
        return self._call("GET", f"{BASE}/personal", params=params)

    def person(self, person_id: int) -> dict:
        return self._call("GET", f"{BASE}/personal/{positive_id(person_id, 'person_id')}")

    def user(self, user_id: int) -> dict:
        return self._call("GET", f"{BASE}/users/{positive_id(user_id, 'user_id')}")

    def tags(self, *, page: int = 1, per_page: int = 50) -> dict:
        self.check_page(page, per_page)
        return self._call("GET", f"{BASE}/personal/tags", params={"page": page, "per_page": per_page})

    def assignments(self, person_id: int) -> dict:
        return self._call("GET", f"{BASE}/personal/{positive_id(person_id, 'person_id')}/assignments")

    def existing_email(self, email: str, *, excluded_person_id: int | None = None) -> list[dict]:
        """Exact-email duplicate check; fails closed if a paginated response is incomplete."""
        matches = []
        page = 1
        while True:
            response = self.persons(page=page, per_page=200, archived="all", email=email)
            data = _data(response, list_expected=True)
            matches.extend({"id": row.get("id"), "is_archived": row.get("is_archived", False)}
                           for row in data if isinstance(row, dict) and isinstance(row.get("email"), str)
                           and row["email"].casefold() == email.casefold()
                           and row.get("id") != excluded_person_id)
            meta = response.get("meta", {})
            pages = meta.get("total_pages")
            if type(pages) is not int or not 0 <= pages <= 10:
                raise RuntimeError("Dublettenabfrage unvollständig; Schreiben abgebrochen")
            if page >= pages:
                return matches
            page += 1

    def ensure_organisation_ids(self, ids: list[int]) -> None:
        for org_id in ids:
            obj = _data(self.organisation(org_id))
            if obj.get("id") != org_id:
                raise RuntimeError("Organisations-ID in API-Antwort widersprüchlich")

    @staticmethod
    def check_page(page: int, per_page: int) -> None:
        if type(page) is not int or not (1 <= page <= 10000):
            raise ValueError("page muss 1..10000 sein")
        if type(per_page) is not int or not (1 <= per_page <= 200):
            raise ValueError("per_page muss 1..200 sein")

    def create_person(self, fields: dict) -> dict:
        return self._call("POST", f"{BASE}/personal", payload=fields, statuses=(201,))

    def update_person(self, person_id: int, fields: dict) -> dict:
        return self._call("PUT", f"{BASE}/personal/{positive_id(person_id, 'person_id')}", payload=fields)

    def bulk_organisations(self, person_ids: list[int], add: list[int], remove: list[int]) -> dict:
        return self._call("POST", f"{BASE}/personal/bulk-organisations",
                          payload={"person_ids": person_ids, "add": add, "remove": remove})
