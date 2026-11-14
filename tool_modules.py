"""Startup-only MCP registration profiles; no changes to REST adapters/contracts."""
from __future__ import annotations

import os
from functools import wraps
from inspect import signature

from management_catalog import OPERATIONS, catalog_status
from mcp_naming import TOOL_NAME_MAP
from v2_core import LOOKUPS

MODULES_ENV = "AUDATIS_MCP_MODULES"
MODULES = {
    "core": "API-/Mandantenmetadaten, Deskriptoren, begrenzte generische Tools und Analysen",
    "assets": "Assets, Kategorien, Typen, Schutzbedarf und Assetgraph",
    "tasks": "Aufgaben und Dublettenprüfung",
    "incidents": "Vorfälle einschließlich Workflows, Unterressourcen und Incident-Beziehungen",
    "risks": "Risikomanagement: ausschließlich dokumentierte Leseoperationen",
    "compliance": "Compliance-Register, Gruppen und Status",
    "measures": "Maßnahmen, Tags und Lookups",
    "isms": "Informationswerte, Geschäftsprozesse und zugehörige Stammdaten",
    "personnel": "Personal, Organisationen und administrative Benutzer lesen",
    "audit": "API-Audit-Log, keine eigenständige Auditverwaltung",
    "reports": "Bisherige Berichts-Liste/-Details über generische core-Tools",
}
TAG_MODULES = {
    "Discovery": "core", "Clients": "core", "Incidents": "incidents",
    "Risks": "risks", "Compliance Registers": "compliance", "Measures": "measures",
    "Information Values": "isms", "Business Processes": "isms", "Audit Log": "audit",
}
RESOURCE_MODULES = {
    "assets": "assets", "tasks": "tasks", "incidents": "incidents", "risks": "risks",
    "information-values": "isms", "business-processes": "isms", "measures": "measures",
    "reports": "reports",
}
OLD_TOOL_MODULES = {
    **dict.fromkeys((
        "list_asset_categories", "list_asset_types", "get_asset", "create_asset",
        "update_asset", "list_asset_protection_levels", "set_asset_protection_needs",
        "list_assets", "asset_graph",
    ), "assets"),
    **dict.fromkeys((
        "create_task", "get_task", "update_task", "list_tasks", "preview_create_task",
        "find_duplicate_tasks",
    ), "tasks"),
    **dict.fromkeys((
        "list_incidents", "list_incident_links", "link_incident",
    ), "incidents"),
    "list_risks": "risks", "list_audit_log": "audit",
    **dict.fromkeys((
        "personnel_capabilities", "list_organisations", "get_organisation",
        "list_personnel", "get_personnel", "create_personnel", "update_personnel",
        "assign_personnel_organisations", "list_personnel_tags", "get_user",
        "get_personnel_assignments", "list_users",
    ), "personnel"),
    **dict.fromkeys((
        "manager_capabilities", "list_records", "get_record", "lookup_values",
        "create_record", "update_record", "bulk_create_records", "bulk_update_records",
        "inventory_snapshot", "documentation_gaps", "relationship_capabilities",
        "relationship_graph", "related_records", "relationship_audit", "bulk_set_parent",
        "management_capabilities", "describe_management_tool",
    ), "core"),
}
GRAPH_MODULES = frozenset({"assets", "isms", "measures", "risks"})
DEPENDENCIES = {
    "inventory_snapshot": GRAPH_MODULES | {"tasks", "incidents"},
    "documentation_gaps": frozenset({"assets", "isms", "measures"}),
    "relationship_graph": GRAPH_MODULES,
    "related_records": GRAPH_MODULES,
    "relationship_audit": GRAPH_MODULES,
}
RESOURCE_TOOLS = frozenset({
    "list_records", "get_record", "create_record", "update_record",
    "bulk_create_records", "bulk_update_records", "bulk_set_parent", "related_records",
})


def parse_modules(value: str | None) -> tuple[str, ...]:
    """Unset means all (compatibility); invalid/empty/mixed-all fails closed."""
    if value is None:
        return ("all",)
    if not isinstance(value, str) or len(value) > 256:
        raise ValueError("AUDATIS_MCP_MODULES: ungültige Konfiguration")
    parts = [part.strip().lower() for part in value.split(",")]
    if not all(parts):
        raise ValueError("AUDATIS_MCP_MODULES darf keine leeren Module enthalten")
    parts = tuple(dict.fromkeys(parts))
    if parts == ("all",):
        return parts
    if "all" in parts or set(parts) - MODULES.keys():
        raise ValueError("AUDATIS_MCP_MODULES: all allein oder Module aus " + ", ".join(MODULES))
    return parts


def canonical_name(name: str) -> str:
    return TOOL_NAME_MAP.get(name, name)


def tool_module(name: str) -> str:
    name = canonical_name(name)
    if name in OLD_TOOL_MODULES:
        return OLD_TOOL_MODULES[name]
    if name in OPERATIONS:
        return TAG_MODULES[OPERATIONS[name]["tags"][0]]
    raise ValueError("MCP-Tool ohne explizite Modulzuordnung: " + name)


def lookup_module(name: str) -> str:
    if not isinstance(name, str) or name not in LOOKUPS:
        raise ValueError("Unbekannter Lookup")
    for prefix, module in (
        ("asset_", "assets"), ("information_", "isms"), ("business_process_", "isms"),
        ("measure_", "measures"), ("task_", "tasks"), ("incident_", "incidents"),
    ):
        if name.startswith(prefix):
            return module
    raise ValueError("Lookup ohne Modulzuordnung")


class ModuleRegistry:
    """Thin registrar proxy around the same MCPServer; selection is immutable per startup."""

    def __init__(self, mcp, selection: str | None = None):
        self._mcp = mcp
        self.requested = parse_modules(selection)
        self.enabled = frozenset(MODULES if self.requested == ("all",) else self.requested)
        self._catalog = {}
        self._finished = False

    def _guard(self, fn):
        name = canonical_name(fn.__name__)
        if self.enabled == frozenset(MODULES):
            return fn  # Preserve all existing contracts, including their error behaviour.
        if name not in RESOURCE_TOOLS | {"lookup_values"}:
            return fn
        sig = signature(fn)

        @wraps(fn)
        def guarded(*args, **kwargs):
            bound = sig.bind(*args, **kwargs)
            bound.apply_defaults()
            try:
                if name == "lookup_values":
                    module = lookup_module(bound.arguments["name"])
                else:
                    resource = bound.arguments["resource"]
                    if not isinstance(resource, str) or resource not in RESOURCE_MODULES:
                        raise ValueError("Unbekannte Ressource")
                    module = RESOURCE_MODULES[resource]
                if module not in self.enabled:
                    return {"ok": False, "tool": fn.__name__, "error_type": "module_disabled",
                            "error": "Fachmodul im Startprofil deaktiviert", "required_module": module}
            except ValueError as exc:
                return {"ok": False, "tool": fn.__name__, "error_type": "validation_error", "error": str(exc)}
            return fn(*args, **kwargs)

        guarded.__signature__ = sig
        return guarded

    def tool(self, *args, **kwargs):
        def register(fn):
            if self._finished:
                raise RuntimeError("Modulregistrierung bereits abgeschlossen")
            name = fn.__name__
            if name in self._catalog:
                raise ValueError("Doppelter MCP-Toolname")
            canonical = canonical_name(name)
            module = tool_module(name)
            dependencies = DEPENDENCIES.get(canonical, frozenset())
            missing = sorted(dependencies - self.enabled)
            enabled = module in self.enabled and not missing
            self._catalog[name] = {
                "module": module, "enabled": enabled,
                "dependencies": sorted(dependencies), "missing_dependencies": missing,
            }
            if enabled:
                self._mcp.tool(*args, **kwargs)(self._guard(fn))
            return fn
        return register

    def finish(self) -> None:
        if self._finished:
            raise RuntimeError("Modulregistrierung bereits abgeschlossen")
        self._finished = True

        def module_capabilities() -> dict:
            """Liest lokal aktivierte Module, registrierte Tools und ausgeblendete Abhängigkeiten."""
            return self.summary()

        self._mcp.tool()(module_capabilities)

    def summary(self) -> dict:
        return {
            "configuration": MODULES_ENV, "requested_modules": list(self.requested),
            "enabled_modules": sorted(self.enabled),
            "available_tools": sorted([name for name, entry in self._catalog.items() if entry["enabled"]]
                                      + (["module_capabilities"] if self._finished else [])),
            "available_tool_count": sum(entry["enabled"] for entry in self._catalog.values()) + int(self._finished),
            "existing_catalog_count": len(self._catalog),
            "local_overview_tool": "module_capabilities",
            "optional_management_catalog": catalog_status(),
            "modules": {
                module: {"enabled": module in self.enabled, "description": description,
                         "available_tools": sorted(n for n, e in self._catalog.items()
                                                   if e["module"] == module and e["enabled"]),
                         "catalog_tools": sorted(n for n, e in self._catalog.items() if e["module"] == module)}
                for module, description in MODULES.items()
            },
            "blocked_dependencies": {name: entry["missing_dependencies"] for name, entry in self._catalog.items()
                                     if entry["module"] in self.enabled and entry["missing_dependencies"]},
            "notes": [
                "module_capabilities ist als lokale Übersicht immer verfügbar.",
                "core-Generiktools erlauben nur aktivierte Ressourcen-/Lookup-Module.",
                "Analysen werden ohne vollständige Modulabhängigkeiten nicht registriert.",
                "Fachliche Links und Felder in erlaubten Antworten werden nicht ausgeblendet.",
                "Toolauswahl ist keine Read-only-Policy und ersetzt keine API-/Rollenberechtigung.",
                "Bestehende Capability-Tools beschreiben Verträge, nicht das aktive Startprofil.",
                "reports verwendet derzeit list_records/get_record und benötigt dafür core.",
            ],
        }
