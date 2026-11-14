"""One unversioned MCP tool per pinned official operation, plus local discovery."""
from __future__ import annotations

from collections.abc import Sequence
from jsonschema import Draft202012Validator
from jsonschema.exceptions import SchemaError

from management_catalog import OPERATIONS, SPEC, get_catalog, permission
from management_core import body_schema, run_operation
from task_direct import EXPECTED_CLIENT_ID


LIMITATIONS = (
    "Risiken: ausschließlich GET; kein Anlegen, Bearbeiten, Löschen oder Behandlungsworkflow.",
    "Keine eigenständige Audit-/Fragebogenverwaltung in dieser OpenAPI; Audit-Log ist kein Auditmodul.",
    "Keine separaten ISMS-/Anforderungskatalog-/SoA-Endpunkte; Compliance-Register, "
    "Geschäftsprozesse, Informationswerte und Maßnahmen sind abgedeckt.",
    "Keine allgemeinen schreibbaren Asset-/Informationswert-/Prozess-/Maßnahmenbeziehungen; "
    "Antwortfelder sind keine Requestfelder. Incident-Links und Parent-Felder sind dokumentiert.",
    "Maßnahmen-Monitoring ist in Antworten enthalten, aber kein freigegebenes Requestfeld.",
    "Schreiboperationen können Benachrichtigungen, Aufgaben und Workflow-Folgen auslösen. "
    "Keine automatische Wiederholung, keine Transaktions- oder Rollbackgarantie.",
)


def management_capabilities() -> dict:
    """Zeigt das additive Management-Paket, Toolkatalog, Berechtigungen und API-Grenzen."""
    return {
        "client_id": EXPECTED_CLIENT_ID, "api_version": SPEC["info"]["version"],
        "openapi_version": SPEC["openapi"], "spec_sha256": get_catalog().sha256,
        "source": "authorized local OpenAPI file",
        "operations": {name: {"method": op["method"], "path": op["path"],
                               "permission": permission(op)}
                       for name, op in OPERATIONS.items()},
        "limitations": list(LIMITATIONS),
        "writes": "execute=false: rein lokale Vorschau; execute=true: echte Operation",
        "incident_mutations": "zusätzlich acknowledge_side_effects=true",
        "deletions": "zusätzlich confirm_delete=true; Token/API-Zugang delete nötig",
        "old_capabilities": "Bestehende Capability-Tools beschreiben unverändert ihre bisherigen Teilpakete.",
    }


def describe_management_tool(tool_name: str) -> dict:
    """Liefert offizielle Parameter, vollständiges Requestschema und Nebenwirkungen eines neuen Tools."""
    if tool_name not in OPERATIONS:
        raise ValueError("Unbekanntes Management-Tool")
    op = OPERATIONS[tool_name]
    media, schema = body_schema(op)
    return {"tool": tool_name, "method": op["method"], "path": op["path"],
            "summary": op.get("summary"), "permission": permission(op),
            "parameters": [p for p in op["parameters"] if p["name"] != "mid"],
            "request_media_type": media, "request_schema": schema,
            "body_required": op.get("requestBody", {}).get("required", False),
            "successful_statuses": [s for s in op["responses"] if s.startswith("2")]}


def _make_tool(name: str, operation: dict):
    media, schema = body_schema(operation)
    if schema is not None:
        Draft202012Validator.check_schema(schema)
    if operation["method"] == "GET":
        def tool(path_params_json: str = "{}", query_json: str = "{}") -> dict:
            return run_operation(name, path_params_json, query_json)
    elif media == "multipart/form-data":
        def tool(file_name: str, file_base64: str, path_params_json: str = "{}",
                 payload_json: str = "{}", execute: bool = False,
                 acknowledge_side_effects: bool = False) -> dict:
            return run_operation(name, path_params_json, payload_json=payload_json,
                                 execute=execute, acknowledge_side_effects=acknowledge_side_effects,
                                 file_name=file_name, file_base64=file_base64)
    else:
        def tool(path_params_json: str = "{}", payload_json: str = "",
                 query_json: str = "{}", execute: bool = False,
                 acknowledge_side_effects: bool = False, confirm_delete: bool = False) -> dict:
            return run_operation(name, path_params_json, query_json, payload_json,
                                 execute=execute, acknowledge_side_effects=acknowledge_side_effects,
                                 confirm_delete=confirm_delete)
    tool.__name__ = name
    tool.__qualname__ = name
    path_keys = [p["name"] for p in operation["parameters"] if p["in"] == "path" and p["name"] != "mid"]
    query_keys = [p["name"] for p in operation["parameters"] if p["in"] == "query"]
    tool.__doc__ = (
        f"{operation.get('summary', name)}. {operation['method']} {operation['path']}.\n"
        f"path_params_json keys: {', '.join(path_keys) or 'none'}; "
        f"query_json keys: {', '.join(query_keys) or 'none'}. "
        "JSON-Objekte; mid ist fest konfiguriert. "
        "Vollständiges Schema: describe_management_tool(tool_name).\n"
        + ("Nur Lesen. Pagination pro Aufruf; meta und alle Seiten beachten."
           if operation["method"] == "GET" else
           "Standard: lokale Vorschau ohne HTTP. Nur execute=true schreibt. "
           "Vorfälle: acknowledge_side_effects=true erforderlich (Mails/SMS/Aufgaben möglich). "
           "DELETE zusätzlich confirm_delete=true. Kein automatischer Retry.\n")
        + "\n" + operation.get("description", "")
    )
    return tool


_tools_catalog = None
_tools = ()


def get_management_tools():
    global _tools_catalog, _tools
    catalog = get_catalog()
    if catalog is _tools_catalog and catalog.status == "available":
        return _tools
    if not OPERATIONS:
        return ()
    try:
        tools = (management_capabilities, describe_management_tool) + tuple(
            _make_tool(name, operation) for name, operation in OPERATIONS.items())
        if len({tool.__name__ for tool in tools}) != len(tools):
            raise ValueError("Duplicate management tool")
        _tools_catalog, _tools = catalog, tools
        return tools
    except (RuntimeError, ValueError, TypeError, KeyError, AttributeError, RecursionError, SchemaError):
        catalog.status = "invalid"
        catalog.operations.clear()
        catalog.spec.clear()
        return ()


class _ManagementTools(Sequence):
    def __len__(self):
        return len(get_management_tools())

    def __getitem__(self, index):
        return get_management_tools()[index]

    def __iter__(self):
        return iter(get_management_tools())


MANAGEMENT_TOOLS = _ManagementTools()
