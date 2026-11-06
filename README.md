# audatisControl

**Unofficial** Model Context Protocol (MCP) server for audatis MANAGER.

Python integration for inventory, tasks, information values, business processes,
measures, documented relationships, security incidents (read/link), personnel
administration, and controlled bulk operations. Read/write operations are limited
by the supplied audatis API credentials and the explicitly configured tenant.

This independent community project is **not affiliated with or endorsed by audatis**.
The audatis MANAGER API specification is **not distributed** in this repository.
Use it only if you have access to an authorised audatis MANAGER instance.

## Setup

1. Python 3.11+ recommended. Create a virtual environment.
2. Install packages: `python -m pip install -r requirements.txt -r requirements-v2.txt`.
3. Copy `.env.example` to `.env` and set your own API host, read token and tenant ID.
4. Set `AUDATIS_ALLOWED_CLIENT_ID` to the tenant ID allowed for write operations.
   Writes fail closed if it is not explicitly configured.
5. Store the write token outside the repository in
   `~/.config/audatis-mcp/write_token` (permissions `chmod 600`).
6. Use `.vscode/mcp.example.json` as a template for your VS Code MCP configuration.
   Replace the Python/script paths with **your** absolute paths, then save it as
   `.vscode/mcp.json`. Do not commit that file.
7. Run offline tests: `python -m pytest -q tests/`.

## Safety

- The MCP server contains **real write operations**. Treat AI-agent instructions as
  potentially actionable. Use a dedicated test tenant and least-privileged tokens.
- Bulk create/update supports preview mode; not every write operation is reversible.
- Existing risk records are read-only through this integration.
- Do not publish `.env`, credential files, real client identifiers, or user data.
- The documented API and permissions may differ across deployments.
- This is source-available code; no open-source license is granted by default.
  Add an appropriate license after choosing terms and checking third-party rights.
