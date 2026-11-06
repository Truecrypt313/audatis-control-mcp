"""Minimal audatis MANAGER MCP server, read-only, tenant-pinned.

Based on audatis API OpenAPI v1.3.0 and official MCP Python SDK v2.
"""
from __future__ import annotations

from mcp.server import MCPServer

from audatis_api import AudatisAPI, summarize_list

mcp = MCPServer("audatisControl")

# nicht mehr notwendig. task:direct fürt befehl create_task() aus task_direct.py aus, der die Aufgabe sofort anlegt.
#from task_approval import prepare_task 
#mcp.tool()(prepare_task)

from task_direct import create_task
mcp.tool()(create_task)

from task_management import get_task, update_task
mcp.tool()(get_task)
mcp.tool()(update_task)

from asset_management import (
    list_asset_categories,
    list_asset_types,
    get_asset,
    create_asset,
)
mcp.tool()(list_asset_categories)
mcp.tool()(list_asset_types)
mcp.tool()(get_asset)
mcp.tool()(create_asset)

from asset_owner_management import list_users, update_asset
mcp.tool()(list_users)
mcp.tool()(update_asset)

from asset_protection import (
    list_asset_protection_levels,
    set_asset_protection_needs,
)
mcp.tool()(list_asset_protection_levels)
mcp.tool()(set_asset_protection_needs)

@mcp.tool()
def list_assets(page: int = 1, per_page: int = 10) -> dict:
    """Liste Assets des konfigurierten audatis-Testmandanten, inkl. Zahl verknüpfter Risiken."""
    result = AudatisAPI.from_env().tenant_get("assets", page=page, per_page=per_page)
    summarized = summarize_list(result, ("id", "title", "category_id", "status_id", "risks", "updated_at"))
    for asset in summarized["data"]:
        risks = asset.pop("risks", None)
        asset["linked_risks_count"] = len(risks) if isinstance(risks, list) else None
    return summarized


@mcp.tool()
def list_risks(page: int = 1, per_page: int = 10, status: str = "") -> dict:
    """Liste Risiken des Testmandanten; Status-Codes laut /risks/statuses."""
    raw = AudatisAPI.from_env().tenant_get(
        "risks", page=page, per_page=per_page, status=status
    )
    return summarize_list(raw, (
        "id", "risk_nr", "designation", "status_code", "risk_type_code",
        "gross_risk", "net_risk",
    ))


@mcp.tool()
def list_tasks(page: int = 1, per_page: int = 10, status: str = "") -> dict:
    """Liste aktive Hauptaufgaben des Testmandanten mit Status und Fälligkeit."""
    raw = AudatisAPI.from_env().tenant_get(
        "tasks", page=page, per_page=per_page, status=status
    )
    return summarize_list(raw, (
        "id", "number", "subject", "status", "priority", "due_date", "is_overdue"
    ))


@mcp.tool()
def list_incidents(page: int = 1, per_page: int = 10, status: str = "") -> dict:
    """Liste Sicherheits-/Datenschutzvorfälle mit Status, Schwere und Zeitstempel."""
    raw = AudatisAPI.from_env().tenant_get(
        "incidents", page=page, per_page=per_page, status=status
    )
    return summarize_list(raw, (
        "id", "incident_number", "title", "status_code", "classification_code",
        "severity", "became_known_at", "next_reporting_deadline_at"
    ))



@mcp.tool()
def preview_create_task(
    subject: str,
    description: str = "",
    priority: str = "normal",
    due_date: str = ""
) -> dict:
    """Bereitet eine neue audatis-Aufgabe vor, ohne sie anzulegen."""
    from datetime import date

    subject = subject.strip()

    if not 1 <= len(subject) <= 255:
        raise ValueError("Aufgabenname muss 1–255 Zeichen haben")

    if priority not in ("none", "low", "normal", "high", "critical"):
        raise ValueError("Ungültige Priorität")

    payload = {
        "subject": subject,
        "description": description,
        "type": "task",
        "status": "open",
        "priority": priority
    }

    if due_date:
        if len(due_date) != 10:
            raise ValueError("Datum muss YYYY-MM-DD sein")
        date.fromisoformat(due_date)
        payload["due_date"] = due_date

    return {
        "mode": "PREVIEW_ONLY",
        "will_write": False,
        "endpoint": "/api/v1/clients/{mid}/tasks",
        "payload": payload,
        "message": "Nur Vorschau. Keine Aufgabe erstellt."
    }

from mcp_naming import named_mcp
from v2_register import register_v2_tools
register_v2_tools(named_mcp(mcp))

from v21_register import register_v21_tools
register_v21_tools(named_mcp(mcp))

from personnel_register import register_personnel_tools
register_personnel_tools(mcp)

if __name__ == "__main__":
    # stdin/stdout for MCP only. Avoid print() and verbose logging to stdout.
    mcp.run(transport="stdio")
