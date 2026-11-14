"""Evidence contracts and deterministic digests; no credentials, HTTP or LLM calls."""
from __future__ import annotations

import hashlib
import json
from copy import deepcopy
from datetime import date, datetime
from zoneinfo import ZoneInfo

from jsonschema import Draft202012Validator, FormatChecker

RESOURCES = ("assets", "information-values", "business-processes", "measures", "risks", "tasks")
STATES = ("complete", "partial", "unavailable", "not_requested")
STATUSES = ("confirmed_finding", "missing_documentation", "not_verifiable")
MAX_JSON = 5 * 1024 * 1024
TEXT = {"type": "string", "maxLength": 1000}
ID = {"type": "string", "minLength": 1, "maxLength": 160}
SCOPE_SCHEMA = {
    "type": "object", "additionalProperties": False, "required": ["name", "object_ids"],
    "properties": {
        "name": ID,
        "object_ids": {"anyOf": [{"type": "null"}, {
            "type": "object", "additionalProperties": False,
            "properties": {r: {"type": "array", "items": ID, "uniqueItems": True, "maxItems": 1000} for r in RESOURCES},
        }]},
    },
}
SOURCE_SCHEMA = {
    "type": "object", "additionalProperties": False,
    "required": ["source_id", "tool", "arguments", "client_reference", "state", "data", "data_sha256"],
    "properties": {
        "source_id": ID, "tool": ID, "arguments": {"type": "object"},
        "client_reference": ID, "state": {"enum": ["ok", "unavailable"]},
        "data": {"anyOf": [{"type": "object"}, {"type": "null"}]},
        "data_sha256": {"type": "string", "pattern": "^[0-9a-f]{64}$"},
        "reason": TEXT,
    },
}
BUNDLE_SCHEMA = {
    "type": "object", "additionalProperties": False,
    "required": ["schema_version", "context", "sources", "resources", "references"],
    "properties": {
        "schema_version": {"const": "1.0"},
        "context": {
            "type": "object", "additionalProperties": False,
            "required": ["organisation", "client_reference", "synthetic", "as_of", "captured_at", "scope"],
            "properties": {
                "organisation": ID, "client_reference": ID, "synthetic": {"type": "boolean"},
                "as_of": {"type": "string", "format": "date"},
                "captured_at": {"type": "string", "format": "date-time"}, "scope": SCOPE_SCHEMA,
            },
        },
        "sources": {"type": "array", "items": SOURCE_SCHEMA, "maxItems": 12000},
        "resources": {
            "type": "object", "required": list(RESOURCES), "additionalProperties": False,
            "properties": {r: {
                "type": "object", "additionalProperties": False,
                "required": ["state", "records", "source_ids", "reason"],
                "properties": {
                    "state": {"enum": list(STATES)}, "reason": TEXT,
                    "records": {"type": "array", "items": ID, "uniqueItems": True, "maxItems": 1000},
                    "source_ids": {"type": "array", "items": ID, "uniqueItems": True, "maxItems": 12000},
                },
            } for r in RESOURCES},
        },
        "references": {
            "type": "object", "additionalProperties": False,
            "properties": {"asset_protection_levels": ID, "asset_statuses": ID},
        },
    },
}


def canonical(value) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False)


def digest(value) -> str:
    return hashlib.sha256(canonical(value).encode("utf-8")).hexdigest()


def parse_json(raw: str, *, maximum: int = MAX_JSON):
    def pairs(items):
        out = {}
        for key, value in items:
            if key in out:
                raise ValueError("Doppelte JSON-Schlüssel")
            out[key] = value
        return out
    def constant(_):
        raise ValueError("Nichtendliche Zahl")
    if not isinstance(raw, str) or len(raw.encode("utf-8")) > maximum:
        raise ValueError("JSON fehlt oder überschreitet das lokale Größenlimit")
    try:
        return json.loads(raw, object_pairs_hook=pairs, parse_constant=constant)
    except (ValueError, RecursionError):
        raise ValueError("Ungültiges JSON; Inhalte werden nicht in Fehlermeldungen übernommen") from None


def validate(schema: dict, value) -> None:
    try:
        error = next(Draft202012Validator(schema, format_checker=FormatChecker()).iter_errors(value), None)
    except (RecursionError, TypeError, ValueError):
        raise ValueError("Nicht auswertbare Eingabestruktur") from None
    if error:
        raise ValueError(f"Eingabe verletzt den Copilot-Vertrag ({error.validator})")


def source(tool: str, arguments: dict, client_reference: str, data: dict | None,
           *, state: str = "ok", reason: str = "") -> dict:
    identity = {"tool": tool, "arguments": arguments, "client": client_reference,
                "data": data, "state": state, "reason": reason}
    return {"source_id": "SRC-" + digest(identity)[:20], "tool": tool,
            "arguments": deepcopy(arguments), "client_reference": client_reference,
            "state": state, "data": deepcopy(data), "data_sha256": digest(data), "reason": reason}


def empty_bundle(organisation: str, as_of: str, captured_at: str, client_reference: str,
                 *, synthetic: bool, scope: dict | None = None) -> dict:
    bundle = {
        "schema_version": "1.0",
        "context": {"organisation": organisation, "as_of": as_of, "captured_at": captured_at,
                    "client_reference": client_reference, "synthetic": synthetic,
                    "scope": scope or {"name": "Gesamter sichtbarer Bestand", "object_ids": None}},
        "sources": [], "references": {},
        "resources": {r: {"state": "not_requested", "records": [], "source_ids": [],
                          "reason": "Nicht beauftragt"} for r in RESOURCES},
    }
    validate(BUNDLE_SCHEMA, bundle)
    return bundle


def validate_bundle(bundle: dict) -> dict:
    validate(BUNDLE_SCHEMA, bundle)
    if sum(len(info["records"]) for info in bundle["resources"].values()) > 1000:
        raise ValueError("Evidence-Bundle überschreitet das lokale Limit von 1000 Objekten")
    if len(canonical(bundle).encode()) > MAX_JSON:
        raise ValueError("Evidence-Bundle überschreitet das lokale Größenlimit")
    if bundle["context"]["synthetic"] and not bundle["context"]["client_reference"].startswith("synthetic:"):
        raise ValueError("Synthetische Fälle müssen einen synthetischen Mandantenbezug tragen")
    as_of = date.fromisoformat(bundle["context"]["as_of"])
    try:
        captured = datetime.fromisoformat(bundle["context"]["captured_at"].replace("Z", "+00:00").replace("z", "+00:00").replace("t", "T"))
        captured_date = captured.astimezone(ZoneInfo("Europe/Berlin")).date()
    except (ValueError, OverflowError):
        raise ValueError("Erfassungszeitpunkt nicht im unterstützten Datumsbereich auswertbar") from None
    if captured_date > as_of:
        raise ValueError("Erfassungsdatum liegt nach dem Bewertungsstichtag; keine rückwirkende IST-Behauptung")
    sources = {}
    for entry in bundle["sources"]:
        if entry["source_id"] in sources:
            raise ValueError("Doppelte Quellen-ID")
        if entry["client_reference"] != bundle["context"]["client_reference"]:
            raise ValueError("Gemischte Mandanten in Evidence-Bundle")
        if entry["data_sha256"] != digest(entry["data"]):
            raise ValueError("Quelleninhalt stimmt nicht mit Prüfsumme überein")
        if entry["state"] == "unavailable" and entry["data"] is not None:
            raise ValueError("Nicht abrufbare Quelle darf keine bestätigten Quelldaten enthalten")
        sources[entry["source_id"]] = entry
    for resource, state in bundle["resources"].items():
        if not set(state["records"]) <= set(state["source_ids"]):
            raise ValueError("Datensatzquelle fehlt im Ressourcen-Quellenverzeichnis")
        if not set(state["source_ids"]) <= sources.keys():
            raise ValueError("Unbekannte Quellenreferenz")
        if state["state"] in ("unavailable", "not_requested") and state["records"]:
            raise ValueError("Nicht erhobene Ressource enthält Datensätze")
        ids = set()
        for sid in state["records"]:
            entry = sources[sid]
            obj = entry["data"]
            if entry["state"] != "ok" or not isinstance(obj, dict) or not isinstance(obj.get("id"), str) or not obj["id"]:
                raise ValueError("Datensatzquelle ohne gültige Objekt-ID")
            if len(obj["id"]) > 160 or obj["id"] in ids:
                raise ValueError("Doppelte oder überlange Objekt-ID")
            if entry["arguments"].get("resource") != resource:
                raise ValueError("Datensatzquelle gehört nicht zur Ressource")
            if entry["tool"] == "get_record" and entry["arguments"].get("record_id") != obj["id"]:
                raise ValueError("Objekt-ID passt nicht zum dokumentierten MCP-Leseaufruf")
            ids.add(obj["id"])
    if not set(bundle["references"].values()) <= sources.keys():
        raise ValueError("Unbekannte Nachschlagequelle")
    return sources


def seal(value: dict, field: str) -> dict:
    body = deepcopy(value)
    return {**body, field: digest(body)}


def verify_seal(value: dict, field: str) -> None:
    if not isinstance(value, dict) or field not in value:
        raise ValueError("Strukturiertes Copilot-Ergebnis fehlt")
    body = {k: v for k, v in value.items() if k != field}
    if value[field] != digest(body):
        raise ValueError("Ergebnis-Prüfsumme abweichend; Bewertung erneut erzeugen")


def assets_only(assessment: dict) -> bool:
    return {r for r, info in assessment["coverage"].items() if info["in_scope"]} == {"assets"}
