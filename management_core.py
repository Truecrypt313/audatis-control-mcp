"""Additive schema-bound transport for the first management integration package.

Existing V2 contracts are untouched. Writes require explicit execution, all incident
mutations require acknowledgement, DELETE additionally needs confirmation. No retry,
redirect, proxy, arbitrary URL, local file access or automatic linked-URL traversal.
"""
from __future__ import annotations

import base64
import binascii
import hashlib
import json
import logging
import re
from copy import deepcopy
from datetime import datetime
from uuid import UUID, uuid4

import httpx
from jsonschema import Draft202012Validator, FormatChecker

from management_catalog import OPERATIONS, SPEC, permission
from task_direct import EXPECTED_CLIENT_ID, _write_token
from v2_core import V2API

LOG = logging.getLogger("audatis.management")
MAX_JSON = 100_000
MAX_FILE = 5 * 1024 * 1024  # MCP safety cap, not an API limit.
MAX_RESPONSE = 10 * 1024 * 1024
FORMATS = FormatChecker()


@FORMATS.checks("date-time")
def _berlin_datetime(value):
    """Official API also accepts offset-free ISO timestamps as Europe/Berlin."""
    if not isinstance(value, str):
        return True
    if not re.fullmatch(r"\d{4}-\d{2}-\d{2}[Tt]\d{2}:\d{2}:\d{2}(?:\.\d+)?(?:[Zz]|[+-]\d{2}:\d{2})?", value):
        return False
    try:
        datetime.fromisoformat(value.replace("t", "T").replace("z", "+00:00").replace("Z", "+00:00"))
        return True
    except ValueError:
        return False


def parse_object(value: str) -> dict:
    def pairs(items):
        result = {}
        for key, item in items:
            if key in result:
                raise ValueError("Doppelte JSON-Schlüssel nicht erlaubt")
            result[key] = item
        return result

    def invalid_constant(_):
        raise ValueError("Nichtendliche Zahlen nicht erlaubt")

    if not isinstance(value, str) or len(value) > MAX_JSON:
        raise ValueError("JSON-Objekt zu groß oder kein Text")
    try:
        data = json.loads(value, object_pairs_hook=pairs, parse_constant=invalid_constant)
    except (ValueError, RecursionError) as exc:
        raise ValueError("Ungültiges JSON-Objekt") from exc
    if type(data) is not dict:
        raise ValueError("JSON-Objekt erwartet")
    return data


def resolve(ref: str) -> dict:
    if not ref.startswith("#/components/schemas/"):
        raise RuntimeError("Externe Schema-Referenz gesperrt")
    return SPEC["components"]["schemas"][ref.rsplit("/", 1)[1]]


def request_schema(schema: dict) -> dict:
    """Convert OAS 3.0 nullable and close request objects, never response schemas."""
    if "$ref" in schema:
        schema = {**deepcopy(resolve(schema["$ref"])), **{k: v for k, v in schema.items() if k != "$ref"}}
    result = deepcopy(schema)
    nullable = result.pop("nullable", False)
    if "properties" in result:
        result["properties"] = {
            key: (False if value.get("readOnly") else request_schema(value))
            for key, value in result["properties"].items()
        }
        result.setdefault("additionalProperties", False)
    if isinstance(result.get("additionalProperties"), dict):
        result["additionalProperties"] = request_schema(result["additionalProperties"])
    if "items" in result:
        result["items"] = request_schema(result["items"])
    for key in ("allOf", "oneOf", "anyOf"):
        if key in result:
            result[key] = [request_schema(part) for part in result[key]]
    if nullable:
        result = {"anyOf": [result, {"type": "null"}]}
    return result


def validate(schema: dict, value, label: str) -> None:
    errors = list(Draft202012Validator(schema, format_checker=FORMATS).iter_errors(value))
    if errors:
        # Do not echo payload values, unknown attacker-controlled keys or server messages.
        error = errors[0]
        location = ".".join(str(x) for x in error.schema_path if x != "properties")
        raise ValueError(f"{label}: Schema-Verletzung ({error.validator}; {location})")


def parameters(operation: dict, path_values: dict, query_values: dict) -> tuple[str, dict]:
    schemas = {"path": {}, "query": {}}
    required = {"path": [], "query": []}
    for param in operation["parameters"]:
        name, place = param["name"], param["in"]
        if place not in schemas:
            raise RuntimeError("Nicht unterstützte Parameterposition")
        if name == "mid":
            continue
        schema = request_schema(param["schema"])
        if place == "path":
            if schema.get("type") == "integer":
                schema = {**schema, "minimum": 1}
            elif schema.get("type") == "string" and schema.get("format") != "uuid":
                schema = {**schema, "pattern": r"^[A-Za-z0-9_-]{1,120}$"}
        if place == "query" and name in ("page", "per_page"):
            schema = {**schema, "minimum": 1, "maximum": 10000 if name == "page" else 200}
        schemas[place][name] = schema
        if param.get("required"):
            required[place].append(name)
    for place, data in (("path", path_values), ("query", query_values)):
        validate({"type": "object", "properties": schemas[place],
                  "required": required[place], "additionalProperties": False}, data, place)
    path = operation["path"].replace("{mid}", str(EXPECTED_CLIENT_ID))
    for name, value in path_values.items():
        if type(value) is str and schemas["path"][name].get("format") == "uuid":
            value = str(UUID(value))
        path = path.replace("{" + name + "}", str(value))
    if "{" in path or not path.startswith("/api/v1"):
        raise RuntimeError("Ungültiger freigegebener Pfad")
    return path, dict(query_values)


def body_schema(operation: dict) -> tuple[str | None, dict | None]:
    content = operation.get("requestBody", {}).get("content", {})
    for media, definition in content.items():
        if media.split(";")[0] in ("application/json", "multipart/form-data"):
            return media.split(";")[0], request_schema(definition["schema"])
    if content:
        raise RuntimeError("Nicht unterstütztes Requestformat")
    return None, None


def prepare(name: str, path_json: str, query_json: str, payload_json: str = "") -> dict:
    if name not in OPERATIONS:
        raise ValueError("Nicht freigegebenes Tool")
    operation = OPERATIONS[name]
    path_values, query = parse_object(path_json), parse_object(query_json)
    path, query = parameters(operation, path_values, query)
    media, schema = body_schema(operation)
    payload = parse_object(payload_json) if payload_json else None
    if schema is None:
        if payload is not None:
            raise ValueError("Operation erlaubt keinen Requestbody")
    elif payload is not None:
        validate(schema, payload, "payload")
        if not payload and operation["method"] == "PUT":
            raise ValueError("Leeres Änderungsobjekt nicht erlaubt")
    elif operation.get("requestBody", {}).get("required"):
        raise ValueError("Requestbody fehlt")
    return {"operation": operation, "path": path, "path_values": path_values, "query": query,
            "payload": payload, "media": media}


class ManagementAPI(V2API):
    """Reuses origin, env/tenant guards, token loading and injectable MockTransport."""

    def perform(self, name: str, prepared: dict, *, file_bytes: bytes | None = None,
                file_name: str = "") -> dict:
        operation = OPERATIONS[name]
        # Revalidate at the transport boundary; do not accept arbitrary prepared URLs.
        expected_path, _ = parameters(operation, prepared["path_values"], prepared["query"])
        if prepared["operation"] != operation or prepared["path"] != expected_path:
            raise ValueError("Operation/Pfad passt nicht zum freigegebenen Tool")
        media, schema = body_schema(operation)
        if schema is not None and prepared["payload"] is not None:
            validate(schema, prepared["payload"], "payload")
        elif schema is not None and operation.get("requestBody", {}).get("required"):
            raise ValueError("Requestbody fehlt")
        elif schema is None and prepared["payload"] is not None:
            raise ValueError("Operation erlaubt keinen Requestbody")
        if (media == "multipart/form-data") != (file_bytes is not None):
            raise ValueError("Multipart-Datei fehlt oder ist nicht erlaubt")
        method = operation["method"]
        token = self.read_token if method == "GET" else (self._write_token_override or _write_token())
        request_id = str(uuid4())
        is_download = any(
            content.get("schema", {}).get("format") == "binary"
            for code, response in operation["responses"].items() if code.startswith("2")
            for content in response.get("content", {}).values()
        )
        headers = {"Authorization": f"Bearer {token}",
                   "Accept": "application/octet-stream" if is_download else "application/json",
                   "X-Request-ID": request_id}
        kwargs = {"params": prepared["query"]}
        if file_bytes is not None:
            kwargs["files"] = {"file": (file_name, file_bytes, "application/octet-stream")}
            kwargs["data"] = {k: v for k, v in prepared["payload"].items() if k != "file"}
        elif prepared["payload"] is not None:
            kwargs["json"] = prepared["payload"]
        success = {int(code) for code in operation["responses"] if code.isdecimal() and 200 <= int(code) < 300}
        LOG.info("audatis request tool=%s method=%s client=%s request_id=%s",
                 name, method, EXPECTED_CLIENT_ID, request_id)
        try:
            with httpx.Client(base_url=self.origin, timeout=30.0, follow_redirects=False,
                              trust_env=False, transport=self._transport) as client:
                with client.stream(method, prepared["path"], headers=headers, **kwargs) as response:
                    status = response.status_code
                    LOG.info("audatis response tool=%s status=%s request_id=%s", name, status, request_id)
                    if status not in success:
                        hints = {401: "Token ungültig", 403: "API-/Mandanten-/Modulrecht prüfen",
                                 404: "Nicht gefunden oder nicht zugänglich", 409: "Konflikt",
                                 422: "API-Validierung oder Workflow-Voraussetzung",
                                 429: "Rate-Limit; kein automatischer Retry"}
                        raise RuntimeError(f"audatis HTTP {status}: {hints.get(status, 'Anfrage fehlgeschlagen')}; "
                                           "Remote-Zustand vor Wiederholung prüfen")
                    chunks, size = [], 0
                    for chunk in response.iter_bytes():
                        size += len(chunk)
                        if size > MAX_RESPONSE:
                            raise RuntimeError("Antwort überschreitet MCP-Limit; Zustand vor Wiederholung prüfen")
                        chunks.append(chunk)
                    content = b"".join(chunks)
                    media = response.headers.get("content-type", "").split(";")[0].strip()
        except httpx.RequestError:
            LOG.warning("audatis transport_error tool=%s request_id=%s", name, request_id)
            raise RuntimeError("Netzwerkfehler; Ergebnis ggf. ungewiss. Remote-Zustand prüfen; kein Auto-Retry") from None
        result = {"ok": True, "client_id": EXPECTED_CLIENT_ID, "tool": name,
                  "http_status": status, "request_id": request_id, "will_write": method != "GET"}
        if status == 204:
            return {**result, "deleted": True}
        response_content = operation["responses"][str(status)].get("content", {})
        binary = any(v.get("schema", {}).get("format") == "binary" for v in response_content.values())
        if binary:
            return {**result, "content_type": media, "size_bytes": size,
                    "sha256": hashlib.sha256(content).hexdigest(),
                    "content_base64": base64.b64encode(content).decode("ascii")}
        if media != "application/json" and not media.endswith("+json"):
            raise RuntimeError("Unerwarteter Antworttyp; Zustand vor Wiederholung prüfen")
        try:
            body = json.loads(content)
        except (ValueError, RecursionError):
            raise RuntimeError("Ungültige JSON-Antwort; Zustand vor Wiederholung prüfen") from None
        if not isinstance(body, dict) or "data" not in body:
            raise RuntimeError("Unerwartete API-Antwort; Zustand vor Wiederholung prüfen")
        # Never follow server-provided _links or _actions.
        return {**result, "response": body}


def run_operation(name: str, path_params_json: str = "{}", query_json: str = "{}",
                  payload_json: str = "", *, execute: bool = False,
                  acknowledge_side_effects: bool = False, confirm_delete: bool = False,
                  file_base64: str = "", file_name: str = "") -> dict:
    for flag in (execute, acknowledge_side_effects, confirm_delete):
        if type(flag) is not bool:
            raise ValueError("Ausführungs-/Bestätigungsflags müssen Boolean sein")
    if name not in OPERATIONS:
        raise ValueError("Nicht freigegebenes Tool")
    operation = OPERATIONS[name]
    file_bytes = None
    if body_schema(operation)[0] == "multipart/form-data":
        if (not isinstance(file_name, str) or not 1 <= len(file_name) <= 150
                or any(c in file_name for c in ("/", "\\", "\r", "\n", "\x00", '"'))
                or file_name in (".", "..")):
            raise ValueError("Sicherer Dateiname mit 1..150 Zeichen erforderlich")
        if not isinstance(file_base64, str) or len(file_base64) > 4 * ((MAX_FILE + 2) // 3):
            raise ValueError("Datei überschreitet MCP-Uploadlimit")
        try:
            file_bytes = base64.b64decode(file_base64, validate=True)
        except (ValueError, binascii.Error):
            raise ValueError("Ungültige Base64-Datei") from None
        if not file_bytes or len(file_bytes) > MAX_FILE:
            raise ValueError("Datei leer oder zu groß")
        payload = parse_object(payload_json or "{}")
        if "file" in payload:
            raise ValueError("file wird ausschließlich aus file_base64 übernommen")
        payload_json = json.dumps({**payload, "file": file_name})
    elif file_base64 or file_name:
        raise ValueError("Dateiargumente nur beim dokumentierten Multipart-Upload")
    prepared = prepare(name, path_params_json, query_json, payload_json)
    writes = operation["method"] != "GET"
    if writes and not execute:
        return {"ok": True, "mode": "preview", "will_write": False,
                "client_id": EXPECTED_CLIENT_ID, "tool": name,
                "method": operation["method"], "path": prepared["path"],
                "payload_fields": sorted((prepared["payload"] or {}).keys()),
                "permission": permission(operation),
                "warning": "Nur lokale Schema-Prüfung; keine Live-Vorprüfung. "
                           "Workflow, Fremd-IDs, Archivstatus und Berechtigung prüft die API."}
    if writes and "Incidents" in operation.get("tags", []) and not acknowledge_side_effects:
        raise ValueError("Vorfälle können Mails/SMS/Aufgaben auslösen; acknowledge_side_effects=true erforderlich")
    if operation["method"] == "DELETE" and not confirm_delete:
        raise ValueError("DELETE erfordert zusätzlich confirm_delete=true")
    return ManagementAPI.from_env().perform(name, prepared, file_bytes=file_bytes, file_name=file_name)
