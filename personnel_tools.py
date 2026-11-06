"""Unversioned MCP tool names for personnel and organisation management.

'Personal' records are not login-enabled administrative system users.
All writes are opt-in execute=True, tenant-pinned, with no deletes or mail sending.
"""
from __future__ import annotations

from personnel_core import (
    PersonnelAPI, CREATE_FIELDS, UPDATE_FIELDS, MAX_BULK_PERSONS,
    _data, _validated, ids_json, positive_id, validate_create, validate_update,
)
from v2_core import EXPECTED_CLIENT_ID


PERSON_FIELDS = ("id", "first_name", "last_name", "email", "employee_number", "login",
                 "status", "language", "organisation_ids", "tag_ids", "is_archived")
ORG_FIELDS = ("id", "name", "level", "parent_id")


def _only(data: dict, fields: tuple[str, ...]) -> dict:
    return {key: data.get(key) for key in fields}


def personnel_capabilities() -> dict:
    """Beschreibt verfügbare Personal- und Organisationsfunktionen samt API-Grenzen."""
    return {
        "client_id": EXPECTED_CLIENT_ID,
        "resource": "Personal-/Mitarbeitereinträge, KEINE administrativen Systembenutzer",
        "read_tools": ["list_personnel", "get_personnel", "list_organisations", "get_organisation",
                       "list_personnel_tags", "get_personnel_assignments", "get_user"],
        "write_tools": ["create_personnel", "update_personnel", "assign_personnel_organisations"],
        "create_fields": sorted(CREATE_FIELDS),
        "update_fields": sorted(UPDATE_FIELDS),
        "organisation_ids": "Integer-IDs aus list_organisations, keine UUIDs",
        "person_ids": "Integer-IDs aus list_personnel, keine Systemuser-IDs",
        "bulk_max_persons": MAX_BULK_PERSONS,
        "rules": ["execute=false ist die Standardeinstellung",
                  "update_personnel ersetzt keine Organisations- oder Taglisten",
                  "Keine Benutzerkonto-/Rollenanlage", "Keine Organisationsanlage oder -änderung",
                  "Keine Löschungen, Archivierungen, Mails, Kennwortrücksetzungen oder E-Learning-Zuweisungen",
                  "Keine automatischen Wiederholungen von Schreiboperationen"],
    }


def list_organisations(page: int = 1, per_page: int = 50) -> dict:
    """Liest bestehende Organisationseinheiten mit parent_id; legt keine Organisation an."""
    body = PersonnelAPI.from_env().organisations(page=page, per_page=per_page)
    return {"client_id": EXPECTED_CLIENT_ID, "data": [_only(v, ORG_FIELDS) for v in _data(body, list_expected=True)],
            "meta": body.get("meta", {})}


def get_organisation(organisation_id: int) -> dict:
    """Liest eine vorhandene Organisation anhand der numerischen ID."""
    body = PersonnelAPI.from_env().organisation(positive_id(organisation_id, "organisation_id"))
    return {"client_id": EXPECTED_CLIENT_ID, "data": _only(_data(body), ORG_FIELDS)}


def list_personnel(page: int = 1, per_page: int = 50, archived: str = "false",
                   q: str = "", organisation_id: int = 0) -> dict:
    """Liest Mitarbeiter; optional Textsuche, Archiv- und Organisationsfilter."""
    body = PersonnelAPI.from_env().persons(page=page, per_page=per_page, archived=archived,
                                          q=q, organisation_id=organisation_id)
    return {"client_id": EXPECTED_CLIENT_ID,
            "data": [_only(v, PERSON_FIELDS) for v in _data(body, list_expected=True)],
            "meta": body.get("meta", {})}


def get_personnel(person_id: int) -> dict:
    """Liest einen Mitarbeiterdatensatz (Personal ist nicht gleich Systembenutzer)."""
    body = PersonnelAPI.from_env().person(positive_id(person_id, "person_id"))
    return {"client_id": EXPECTED_CLIENT_ID, "data": _only(_data(body), PERSON_FIELDS)}


def get_user(user_id: int) -> dict:
    """Liest einen bestehenden administrativen Benutzer (nur ID und Name)."""
    body = PersonnelAPI.from_env().user(positive_id(user_id, "user_id"))
    item = _data(body)
    return {"client_id": EXPECTED_CLIENT_ID, "data": {"id": item.get("id"), "name": item.get("name")}}


def list_personnel_tags(page: int = 1, per_page: int = 50) -> dict:
    """Listet vorhandene Mitarbeiter-Tags und deren Sichtbarkeit."""
    body = PersonnelAPI.from_env().tags(page=page, per_page=per_page)
    data = _data(body, list_expected=True)
    return {"client_id": EXPECTED_CLIENT_ID, "data": [
        {key: item.get(key) for key in ("id", "name", "is_visible")} for item in data],
        "meta": body.get("meta", {})}


def get_personnel_assignments(person_id: int) -> dict:
    """Liest bestehende E-Learning-/Zertifikats-/Dokumentationszuweisungen, ohne sie zu ändern."""
    body = PersonnelAPI.from_env().assignments(positive_id(person_id, "person_id"))
    return {"client_id": EXPECTED_CLIENT_ID, "person_id": person_id, "data": body["data"]}


def create_personnel(payload_json: str, execute: bool = False, check_existing: bool = True) -> dict:
    """Erstellt Mitarbeiter (kein Systemlogin!) nach Vorschau und Duplikatprüfung.

    payload_json: z.B. {"last_name":"Test","first_name":"Max","email":"max@example.org",
                      "organisation_ids":[12],"language":"de"}.
    execute=false validiert nur lokal. execute=true prüft bestehende E-Mail und Organisations-IDs.
    Bei Fehler KEINEN automatischen Wiederholungsaufruf starten.
    """
    fields = validate_create(payload_json)
    if type(execute) is not bool or type(check_existing) is not bool:
        raise ValueError("execute und check_existing müssen Boolean sein")
    if not execute:
        return {"ok": True, "mode": "preview", "will_write": False,
                "resource": "personal", "fields": fields,
                "warning": "Vorschau validiert lokal; Dubletten/Organisationen erst bei execute=true"}
    api = PersonnelAPI.from_env()
    api.ensure_organisation_ids(fields.get("organisation_ids", []))
    if check_existing:
        matches = api.existing_email(fields["email"])
        if matches:
            return {"ok": False, "created": False, "error_type": "already_exists",
                    "message": "E-Mail ist bereits einem Personal-Datensatz zugeordnet (auch archiviert)",
                    "existing_ids": [m["id"] for m in matches]}
    data = _data(api.create_person(fields))
    return {"ok": True, "created": True, "client_id": EXPECTED_CLIENT_ID,
            "data": _only(data, PERSON_FIELDS)}


def update_personnel(person_id: int, changes_json: str, execute: bool = False) -> dict:
    """Ändert gezielt Personenstammdaten; Organisationen nur mit assign_personnel_organisations.

    Vor PUT werden die drei laut Schema erforderlichen Namens-/E-Mail-Felder per GET
    geladen. Vorhandene Organisations-, Tag- und Modulzuweisungen bleiben unberührt.
    Eine E-Mail-Änderung kann das Login gemäß audatis-API-Regel ändern.
    """
    positive_id(person_id, "person_id")
    changes = validate_update(changes_json)
    if type(execute) is not bool:
        raise ValueError("execute muss Boolean sein")
    api = PersonnelAPI.from_env()
    current = _data(api.person(person_id))
    if current.get("id") != person_id:
        raise RuntimeError("ID-Abweichung bei Personalabruf")
    if current.get("is_archived"):
        raise ValueError("Archivierte Personen können nicht geändert werden")
    required = ("first_name", "last_name", "email")
    for field in required:
        if not isinstance(current.get(field), str) or not current[field].strip():
            raise RuntimeError("API lieferte benötigte Bestandsfelder unvollständig")
    modified = {k: v for k, v in changes.items() if v != current.get(k)}
    if not modified:
        return {"ok": True, "updated": False, "reason": "no_change", "person_id": person_id}
    payload = {key: current[key] for key in required}
    payload.update(modified)
    _validated("update", payload)
    if not execute:
        return {"ok": True, "mode": "preview", "will_write": False,
                "person_id": person_id, "changes": modified,
                "note": "Es werden nur die drei Pflichtfelder und die angegebenen Änderungen gesendet"}
    if "email" in modified and api.existing_email(modified["email"], excluded_person_id=person_id):
        raise ValueError("Neue E-Mail ist bereits einem Personal-Datensatz zugeordnet")
    result = _data(api.update_person(person_id, payload))
    if result.get("id") != person_id:
        raise RuntimeError("Updateantwort enthält eine andere Person-ID; Remote-Zustand prüfen")
    return {"ok": True, "updated": True, "person_id": person_id,
            "data": _only(result, PERSON_FIELDS)}


def assign_personnel_organisations(person_ids_json: str, add_json: str = "[]",
                                   remove_json: str = "[]", execute: bool = False) -> dict:
    """Bulk-Zuweisung bestehender Mitarbeiter zu bestehenden Organisationen (max. 25 pro Aufruf).

    Beispiel person_ids_json='[12,13]', add_json='[3]', remove_json='[]'.
    Vor dem Schreiben: Existenz, Mandant und Archivstatus ALLER Zielpersonen prüfen.
    Die API kann Teilerfolge liefern, es gibt keinen automatischen Rollback oder Retry.
    """
    person_ids = ids_json(person_ids_json, "person_ids", max_items=MAX_BULK_PERSONS)
    add = ids_json(add_json, "add", allow_empty=True, max_items=100)
    remove = ids_json(remove_json, "remove", allow_empty=True, max_items=100)
    if type(execute) is not bool:
        raise ValueError("execute muss Boolean sein")
    if not (add or remove):
        raise ValueError("Mindestens eine Organisations-ID in add oder remove erforderlich")
    if set(add) & set(remove):
        raise ValueError("Organisation darf nicht zugleich in add und remove stehen")
    api = PersonnelAPI.from_env()
    api.ensure_organisation_ids(sorted(set(add) | set(remove)))
    current = {}
    for person_id in person_ids:
        entry = _data(api.person(person_id))
        if entry.get("id") != person_id or entry.get("is_archived"):
            raise ValueError(f"person_id {person_id}: nicht vorhanden oder archiviert")
        old = entry.get("organisation_ids")
        if type(old) is not list or not all(type(v) is int for v in old):
            raise RuntimeError("Organisationen des Personal-Datensatzes nicht lesbar")
        current[person_id] = set(old)
    changes = {}
    for person_id, org_ids in current.items():
        target = (org_ids | set(add)) - set(remove)
        if target != org_ids:
            changes[person_id] = {"before": sorted(org_ids), "after": sorted(target)}
    if not execute:
        return {"ok": True, "mode": "preview", "will_write": False,
                "person_ids": person_ids, "add": add, "remove": remove,
                "changes": changes, "changed_count": len(changes)}
    if not changes:
        return {"ok": True, "completed": True, "updated": False, "reason": "no_change"}
    result = _data(api.bulk_organisations(person_ids, add, remove))
    summary = result.get("summary", {})
    results = result.get("results")
    if not isinstance(summary, dict) or not isinstance(results, list):
        raise RuntimeError("Bulk-Antwort unvollständig; Remote-Zustand prüfen")
    failures = sum(summary.get(k, 0) for k in ("not_found", "archived"))
    return {"ok": failures == 0, "completed": failures == 0,
            "client_id": EXPECTED_CLIENT_ID, "summary": summary,
            "results": results, "warning": "Bulk-API verarbeitet pro Person; Teilerfolge möglich. Kein Auto-Retry."}
