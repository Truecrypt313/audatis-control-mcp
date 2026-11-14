# Tool profiles

Set `AUDATIS_MCP_MODULES` before starting the main server. Unset means `all`;
empty, unknown or mixed `all,...` selections are rejected. Restart after changes.

Available groups are `core`, `assets`, `tasks`, `incidents`, `risks`,
`compliance`, `measures`, `isms`, `personnel`, `audit` and `reports`.
For example, `core,assets,tasks` selects those groups without implicitly enabling
others. `reports` uses the generic reading tools in `core`.

- Base `all`: 48 tools, including `module_capabilities`.
- Extended `all` with the reviewed API 1.3.1 contract: 227 tools.
- Restricted profile counts depend on the selected groups and catalog availability.
- The separate Copilot always registers its own seven tools; it is not another
  main-server profile.

`module_capabilities()` is local metadata: it reports registered names, group
selection, unmet analysis dependencies and optional catalog status without HTTP.
Do not infer a missing feature's availability from an old static descriptor.

Generic resource and lookup tools enforce the enabled resource groups before
credential access. Cross-resource analyses require all their documented groups;
they do not silently analyse an incomplete subset.

Profiles are not access control, redaction or read-only enforcement. Some tools
can write immediately; optional management mutations default to a local preview.
API rights, tenant guards, separate credentials, explicit execution and any
incident/deletion acknowledgements still apply.
