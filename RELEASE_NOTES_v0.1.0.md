# audatisControl v0.1.0 — Initial public release

First public, source-available release of **audatisControl**, an unofficial Python MCP server for audatis MANAGER.

## Included

- MCP integration with **47 tools** using consistent public names in `modern` mode.
- Read and write operations for supported assets, tasks, information values, business processes, and measures.
- Documentation audits, inventory snapshots, relationship graphs, and asset/process hierarchies.
- Controlled batch creation and updates with preview support.
- Personnel records, organisation lookups and assignment workflows.
- Incident reading and supported incident-object links.
- Tenant-scoped API credentials and documentation for separating read/write tokens.
- Offline tests (`python -m pytest -q tests/`).

## Licensing

**Free for noncommercial use** under [PolyForm Noncommercial 1.0.0](LICENSE.md). Commercial use requires a separately negotiated **paid commercial license**; see [COMMERCIAL-LICENSING.md](COMMERCIAL-LICENSING.md).

## Notes

- This is an **unofficial**, independently maintained integration, not affiliated with or endorsed by audatis.
- No API tokens, real tenant IDs, private server addresses, or audatis API specification are bundled.
- Some tools perform real writes. Review credentials, permissions, and selected tenant before using them.
- API compatibility and permissions depend on the audatis MANAGER deployment.
