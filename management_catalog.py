"""Optional, local-only OpenAPI catalog. Importing this module never reads a file."""
from __future__ import annotations

import hashlib
import json
import os
import re
from collections.abc import Mapping
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

SPEC_PATH = Path(__file__).with_name("specs") / "audatis-openapi-1.3.1.json"
SPEC_SHA256 = "913fcca36bcdff5342f2cd899c29a8699866738f143835e2fe64f1d53008bbd4"
PACKAGE_TAGS = frozenset({
    "Risks", "Incidents", "Compliance Registers", "Measures",
    "Business Processes", "Information Values", "Audit Log",
})
METHODS = frozenset({"get", "post", "put", "delete"})
# Preserve the existing 47 public names AND their signatures/behaviour.
NAME_OVERRIDES = {
    "listRisks": "query_risks",
    "listIncidents": "query_incidents",
    "listAuditLog": "query_audit_log",
    "apiRoot": "get_api_info",
    "getMandant": "get_client_info",
}


def snake_case(name: str) -> str:
    name = re.sub(r"(.)([A-Z][a-z]+)", r"\1_\2", name)
    return re.sub(r"([a-z0-9])([A-Z])", r"\1_\2", name).lower()


def _pairs(items):
    result = {}
    for key, value in items:
        if key in result:
            raise ValueError("Duplicate key")
        result[key] = value
    return result


def _validate_spec(spec):
    if (not isinstance(spec, dict) or spec.get("openapi") != "3.0.0"
            or not isinstance(spec.get("info"), dict)
            or spec["info"].get("version") != "1.3.1"
            or not isinstance(spec.get("paths"), dict) or not spec["paths"]
            or not isinstance(spec.get("components"), dict)
            or not isinstance(spec["components"].get("schemas"), dict)):
        raise ValueError("Unsupported version or structure")
    def references(value):
        if isinstance(value, dict):
            if "$ref" in value:
                ref = value["$ref"]
                if (not isinstance(ref, str) or not ref.startswith("#/components/schemas/")
                        or ref.rsplit("/", 1)[-1] not in spec["components"]["schemas"]):
                    raise ValueError("External or unresolved reference")
            for child in value.values():
                references(child)
        elif isinstance(value, list):
            for child in value:
                references(child)
    references(spec)
    identifiers = set()
    for path, item in spec["paths"].items():
        if (not isinstance(path, str) or not path.startswith("/api/v1")
                or any(c in path for c in ("?", "#", "%", "\\"))
                or ".." in path or not isinstance(item, dict)
                or not isinstance(item.get("parameters", []), list)):
            raise ValueError("Invalid path")
        for method, operation in item.items():
            if method not in METHODS:
                continue
            if (not isinstance(operation, dict)
                    or not re.fullmatch(r"[A-Za-z][A-Za-z0-9_]*", operation.get("operationId", ""))
                    or operation["operationId"] in identifiers
                    or not isinstance(operation.get("tags"), list) or not operation["tags"]
                    or not all(isinstance(t, str) for t in operation["tags"])
                    or not isinstance(operation.get("parameters", []), list)
                    or not isinstance(operation.get("responses"), dict)
                    or not isinstance(operation.get("requestBody", {}), dict)
                    or not any(re.fullmatch(r"2[0-9]{2}", str(s)) for s in operation["responses"])):
                raise ValueError("Invalid operation")
            identifiers.add(operation["operationId"])
            if (PACKAGE_TAGS.intersection(operation["tags"])
                    and operation["tags"][0] not in PACKAGE_TAGS):
                raise ValueError("Unsupported operation group")
            if path in ("/api/v1", "/api/v1/clients/{mid}") and operation["tags"][0] not in ("Discovery", "Clients"):
                raise ValueError("Unsupported metadata group")
            for parameter in item.get("parameters", []) + operation.get("parameters", []):
                if (not isinstance(parameter, dict) or not isinstance(parameter.get("name"), str)
                        or parameter.get("in") not in ("path", "query", "header", "cookie")
                        or not isinstance(parameter.get("schema"), dict)):
                    raise ValueError("Invalid parameter")
            if "Risks" in operation["tags"] and method != "get":
                raise ValueError("Risk writes are not supported")


def load_spec(path=None, expected_sha256=None) -> dict:
    """Read one explicitly trusted local file, never a URL or a remote reference."""
    path = Path(path) if path is not None else SPEC_PATH
    expected = SPEC_SHA256 if expected_sha256 is None else expected_sha256
    try:
        if not re.fullmatch(r"[0-9a-f]{64}", expected):
            raise ValueError("Invalid digest")
        if path.is_symlink() or not path.is_file() or path.stat().st_size > 8 * 1024 * 1024:
            raise ValueError("Invalid local file")
        raw = path.read_bytes()
        if hashlib.sha256(raw).hexdigest() != expected:
            raise RuntimeError("OpenAPI-Prüfsumme abweichend; keine automatische Vertragsänderung")
        spec = json.loads(raw, object_pairs_hook=_pairs,
                          parse_constant=lambda _: (_ for _ in ()).throw(ValueError("Nonfinite value")))
        _validate_spec(spec)
        return spec
    except RuntimeError:
        raise
    except (OSError, ValueError, TypeError, RecursionError):
        raise RuntimeError("Lokale OpenAPI-Datei nicht auswertbar; Version, Struktur und Zugriff prüfen") from None


@dataclass
class Catalog:
    spec: dict
    operations: dict
    status: str
    sha256: str | None = None


def build_operations(spec: dict) -> dict:
    operations = {}
    for path, item in spec["paths"].items():
        for method, definition in item.items():
            if method not in METHODS:
                continue
            if not (PACKAGE_TAGS.intersection(definition.get("tags", []))
                    or path in ("/api/v1", "/api/v1/clients/{mid}")):
                continue
            operation_id = definition["operationId"]
            name = NAME_OVERRIDES.get(operation_id, snake_case(operation_id))
            if name in operations:
                raise RuntimeError("Doppelter Management-Toolname")
            operations[name] = {
                **definition, "path": path, "method": method.upper(),
                "parameters": item.get("parameters", []) + definition.get("parameters", []),
            }
    return operations


@lru_cache(maxsize=1)
def get_catalog() -> Catalog:
    # Unset preserves the existing private development location. Empty disables it.
    # The public distribution never contains this file or a replacement catalog.
    configured = os.environ.get("AUDATIS_OPENAPI_SPEC_PATH")
    if configured == "":
        return Catalog({}, {}, "disabled")
    try:
        path = Path(configured).expanduser() if configured is not None else SPEC_PATH
        if not path.exists():
            return Catalog({}, {}, "missing")
        digest = os.environ.get("AUDATIS_OPENAPI_SPEC_SHA256", SPEC_SHA256)
        spec = load_spec(path, digest)
        operations = build_operations(spec)
        return Catalog(spec, operations, "available", digest)
    except (OSError, RuntimeError, ValueError, TypeError, KeyError, RecursionError):
        # Never expose filenames, schema contents or underlying exceptions in MCP.
        return Catalog({}, {}, "invalid")


def catalog_status() -> dict:
    catalog = get_catalog()
    return {"status": catalog.status, "available": catalog.status == "available",
            "operation_count": len(catalog.operations),
            "source_configuration": "AUDATIS_OPENAPI_SPEC_PATH",
            "restart_required_after_changes": True}


class _LazyMapping(Mapping):
    def __init__(self, attribute):
        self.attribute = attribute

    def __getitem__(self, key):
        return getattr(get_catalog(), self.attribute)[key]

    def __iter__(self):
        return iter(getattr(get_catalog(), self.attribute))

    def __len__(self):
        return len(getattr(get_catalog(), self.attribute))


SPEC = _LazyMapping("spec")
OPERATIONS = _LazyMapping("operations")


def permission(operation: dict) -> dict:
    method = operation["method"]
    level = {"GET": "read", "POST": "write", "PUT": "write", "DELETE": "delete"}[method]
    return {
        "token_scope": level, "api_access": level,
        "module": operation.get("tags", []),
        "module_rule": ("Administration: Lesen" if "Audit Log" in operation.get("tags", [])
                        else "Modulrecht und ggf. Datensatzausnahmen gemäß Operationsbeschreibung"),
        "official_description": operation.get("description", ""),
    }
