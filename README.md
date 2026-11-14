# audatisControl

**Unofficial MCP integration for audatis MANAGER**

## Overview

audatisControl connects MCP-compatible assistants to the audatis MANAGER REST API
using Python for controlled administration and deterministic ISMS analysis.
**Independent project; not an official extension or endorsed by audatis.**

## Features

- **Base mode:** 47 existing integration tools plus the local module overview
  (**48 tools** with `all`).
- **Extended mode:** **227 tools** with the reviewed, authorized API **1.3.1**
  specification, including incident, measure, process and compliance operations.
- Configurable tool groups through `AUDATIS_MCP_MODULES`, supported bulk
  operations, documented relationships and read-only risk access.
- **7 separate ISMS Consulting Copilot tools** for evidence-based assessments,
  remediation proposals and reproducible Markdown/HTML reports.
- Three-asset demo with a preview/approval pause and at most three recommendations.

## Architecture

`server.py` exposes the main MCP/stdio server. Its optional local catalog loads
on demand; missing or invalid specifications leave base tools available.
`copilot_server.py` runs independently, without AI-service calls or API writes.

## Quick Start

Use Python **3.11+**. Run `python3 -m venv .venv`, then
`.venv/bin/python -m pip install -r requirements.txt -r requirements-v2.txt`.
Copy `.env.example` to a private `.env`; configure the HTTPS origin, credentials,
active tenant and allowed-tenant guard.

Configure separate stdio entries in your MCP client using absolute interpreter
and script paths: `.venv/bin/python` with `server.py`, or `copilot_server.py`.
Set `AUDATIS_MCP_TOOL_NAMES=modern`; use `AUDATIS_MCP_MODULES=all` for the full
profile.

**No audatis MANAGER API specification is distributed.** For extended mode,
set `AUDATIS_OPENAPI_SPEC_PATH` to your own authorized local copy. Version,
structure and checksum are checked. Restart after configuration changes.

## Security

Use least-privilege credentials, aligned tenant guards and separate protected
write credentials. New management writes require explicit execution; incidents
and deletions have additional confirmations. Legacy immediate-write tools remain.
Profiles are **not read-only enforcement**. No automatic bulk rollback or retry.
Never commit secrets or customer data. Findings are not compliance certifications.

## Documentation

- [Setup and optional specification](docs/PUBLIC_SETUP.md)
- [Tool groups](docs/PUBLIC_TOOL_MODULES.md)
- [ISMS Consulting Copilot](docs/PUBLIC_COPILOT.md)
- [Three-instruction asset demo and short report](docs/ASSET_DEMO.md)
- [Security and distribution boundaries](docs/PUBLICATION_SECURITY.md)

Run `.venv/bin/python -m pytest -q tests/` for offline tests.

## License

[PolyForm Noncommercial 1.0.0](LICENSE.md) and [required notice](NOTICE).
Commercial use outside its permissions requires a separate
[commercial agreement](COMMERCIAL-LICENSING.md). Third-party rights remain unchanged.
