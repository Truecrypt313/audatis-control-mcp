# audatisControl

**Unofficial MCP server for AI-assisted audatis MANAGER administration**

[License: PolyForm Noncommercial 1.0.0](LICENSE.md) · [Commercial licensing](COMMERCIAL-LICENSING.md) · [First release notes](RELEASE_NOTES_v0.1.0.md)

audatisControl is a Python [Model Context Protocol (MCP)](https://modelcontextprotocol.io/) server that connects MCP-compatible AI clients (such as GitHub Copilot in VS Code) to the **audatis MANAGER REST API**. Ask your assistant to inspect assets, review documentation quality, manage supported records, and carry out controlled bulk operations.

> **Independent project:** This repository is not affiliated with, sponsored by, or endorsed by audatis. audatis MANAGER and related trademarks belong to their respective owners. This repository does not distribute the vendor's API specification.

## Features

| Area | Capabilities |
| --- | --- |
| IT assets | List, create, update, owner assignments, protection overrides, supported parent/child hierarchy |
| Tasks | List, create, update, prioritise, inspect potential duplicates |
| Information values | Read and manage supported information records |
| Business processes | Read, create, update, inspect and manage parent/child hierarchy |
| Security measures | Read, create, update, assess documented coverage |
| Risks | Read and analyse available risk records; **no risk-writing endpoint implemented** |
| Incidents | Read incidents and manage supported links to existing records; **no incident creation** |
| Personnel | Read, create, update personnel records; assign them to existing organisations |
| Organisations and users | Read existing organisation units and administrative users; **no account or organisation creation** |
| Analysis | Inventory snapshots, documentation gaps, relationship graph and audit |
| Bulk operations | Preview, validate and execute selected batched create/update operations |

**47 MCP tools** are currently registered. Set `AUDATIS_MCP_TOOL_NAMES=modern` for consistent public names without the older `v2_` and `v21_` prefixes. The original names remain available with `legacy` mode for compatibility.

### Example prompts

These examples assume that the MCP server is connected to your AI client:

- `Use list_assets and documentation_gaps to find incomplete asset documentation. Do not modify anything.`
- `Use relationship_graph and related_records to show the documented dependencies of this asset.`
- `Use list_personnel and list_organisations to show personnel assignments. Read-only.`
- `Preview creating two test tasks via bulk_create_records with execute=false. Do not execute writes.`
- `Use manager_capabilities and lookup_values to determine valid fields and status codes before preparing updates.`

The AI client may select the underlying tool based on natural-language instructions; these names are **MCP tools, not shell commands**.

## Architecture

```text
MCP-compatible AI client (e.g. VS Code / GitHub Copilot)
             |
           stdio
             |
    audatisControl (Python MCP server)
      |     |     |
    Tools  Validation  Tenant guard
             |
       audatis MANAGER REST API
```

The integration **does not** perform automatic network discovery. Graphs represent relationships already documented in audatis MANAGER.

## Quick start

Requirements: **Python 3.11+**, a permitted audatis MANAGER API endpoint, and valid API credentials.

```bash
git clone https://github.com/Truecrypt313/audatis-control-mcp.git
cd audatis-control-mcp
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -r requirements.txt -r requirements-v2.txt
cp .env.example .env
```

Edit `.env` locally:

```dotenv
AUDATIS_BASE_URL=https://your-audatis-host.example
AUDATIS_CLIENT_ID=12345
AUDATIS_ALLOWED_CLIENT_ID=12345
AUDATIS_API_TOKEN=YOUR_READ_ONLY_TOKEN
AUDATIS_MCP_TOOL_NAMES=modern
```

- `AUDATIS_CLIENT_ID` selects the tenant.
- `AUDATIS_ALLOWED_CLIENT_ID` explicitly scopes supported write operations. **Never point writable credentials at a production tenant without appropriate controls.**
- `AUDATIS_API_TOKEN` is the read API credential.
- Store a **separate write token**, if needed, in `~/.config/audatis-mcp/write_token` with restrictive permissions:

```bash
mkdir -p ~/.config/audatis-mcp
chmod 700 ~/.config/audatis-mcp
# Add your write token using a local editor; do not paste it into chat or Git.
chmod 600 ~/.config/audatis-mcp/write_token
```

Use [`.vscode/mcp.example.json`](.vscode/mcp.example.json) as a template for your local `.vscode/mcp.json`. Replace the placeholder absolute Python and `server.py` paths. Keep the example and real configuration separate; **never commit a machine-specific configuration containing secrets**.

For direct stdio execution:

```bash
.venv/bin/python server.py
```

A stdio MCP server communicates through its protocol; it does not normally print a human-readable application menu in this mode. Start it through your configured MCP client.

## Testing

```bash
source .venv/bin/activate
python -m pytest -q tests/
```

The offline test suite uses simulated API interactions. It cannot confirm your server's actual permissions or live audatis MANAGER compatibility. Test live writes only in a dedicated, authorised tenant.

## Security & operational limitations

- **Real writes are possible**: Creating or changing records can affect persistent data. Preview first when supported.
- **Tenant scope**: Configure both the active and permitted write-tenant IDs. Use narrowly scoped credentials; confirm each legacy/specialised tool's permissions before deployment.
- **No transactional bulk rollback**: An individual write can succeed even if a subsequent write fails. Verify remote state before attempting retries.
- **No arbitrary API proxy**: Only supported resource types and fields are exposed by the tools.
- **Privacy**: Never commit credentials, real customer data, internal hostnames, or local MCP configuration.
- **Not a compliance verdict**: Documentation-gap and relationship findings are heuristic indicators, not an audit certification or a substitute for professional security assessment.
- **API coverage**: Users cannot create administrative accounts or organisation units through this implementation; risks are read-only; incident functionality is limited to reading and supported links.

## License and commercial use

The software is **source-available**, not OSI-approved open source:

- **Noncommercial use:** Free under the [PolyForm Noncommercial License 1.0.0](LICENSE.md), including permitted personal, hobby, educational, and other noncommercial uses as defined by that license.
- **Commercial use:** Requires a **separately negotiated paid license**. See [Commercial Licensing](COMMERCIAL-LICENSING.md).
- Third-party dependencies and the audatis MANAGER service retain their own licenses and conditions.

Copyright © 2026 Truecrypt313. See [NOTICE](NOTICE).

## Project status

Early public release. Contributions, feedback, and bug reports are welcome through [GitHub Issues](https://github.com/Truecrypt313/audatis-control-mcp/issues). Please report security-sensitive findings privately rather than posting secrets or exploit details in public issues.
