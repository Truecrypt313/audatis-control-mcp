# Setup and optional local API contract

This independent integration does not include a vendor specification, complete
generated replacement schema, private instance configuration or customer export.
Use Python 3.11+ and install both requirements files in a virtual environment.

## Base mode

The main server registers the existing 47 integration tools and
`module_capabilities`: 48 tools in `all`, before applying any restricted profile.
Set `AUDATIS_OPENAPI_SPEC_PATH` to the empty string to explicitly disable the
optional catalog. A fresh public clone contains no specification.

Configure `AUDATIS_BASE_URL` with an authorized HTTPS origin and
`AUDATIS_API_TOKEN` with the least-privilege read credential. In the public
distribution, `AUDATIS_ALLOWED_CLIENT_ID` pins the approved tenant and
`AUDATIS_CLIENT_ID` must match it. Use positive IDs from your authorized
deployment; the default allowed ID is 0, which disables tenant operations.
The example number is synthetic, not a configured customer.

Protect any separate write token with restrictive file permissions. A read token
alone does not disable legacy tools which use the separate credential.

## Extended mode

Obtain API documentation yourself through an authorized vendor channel under
its applicable terms. Set `AUDATIS_OPENAPI_SPEC_PATH` to the local JSON file.
Do not upload it to GitHub or include it in issue reports.

The loader checks OpenAPI 3.0.0, API version 1.3.1, structural requirements,
local-only resolvable schema references and the reviewed SHA-256 pin. It never
downloads anything or trusts the specification's `servers` URLs. Without an
explicit path, the historical private `specs/audatis-openapi-1.3.1.json` location
is checked on demand; that directory is excluded from Git.

The default pin in `management_catalog.py` identifies the contract used for the
227-tool integration test. A different locally reviewed contract requires
an explicit `AUDATIS_OPENAPI_SPEC_SHA256` override. Never copy an untrusted
file's checksum merely to bypass review. Different contracts do not imply the
same tool count or vendor compatibility.

Missing, unreadable, malformed, unsupported or checksum-mismatched contracts
disable the whole optional package, not the base server. Check
`module_capabilities().optional_management_catalog` for a sanitized status.
No filename or schema content is returned there. Restart to change catalogs.

## MCP configuration

Use a stdio-capable client. Configure the absolute virtual-environment Python
path as the command and the absolute `server.py` path as its argument.
For the independent Copilot, configure a second process with `copilot_server.py`.
The paths in the example are placeholders, not personal filesystem paths.
Store credentials using your client's approved private secret mechanism.
For the asset demonstration, use `AUDATIS_MCP_MODULES=core,assets` on the main
server (20 base / 24 extended tools); the independent Copilot still has seven tools.
See [ASSET_DEMO.md](ASSET_DEMO.md).

`AUDATIS_MCP_TOOL_NAMES=modern` selects the public aliases;
`AUDATIS_MCP_MODULES=all` enables all tools available in the selected mode.
Module profiles do not grant API access or make the server read-only.

## Tests

Run `python -m pytest -q tests/` from the repository with the dependencies installed.
The public suite uses mocks, blocked network connections and two hand-written
synthetic catalog operations. It needs no vendor file or pre-generated reports.
Vendor-contract tests are explicitly skipped without the separately supplied
177-operation contract; skips are not compatibility evidence.

For a private, fully offline contract run, set both `AUDATIS_OPENAPI_SPEC_PATH`
and `AUDATIS_TEST_VENDOR_SPEC_PATH` to your authorized local file before invoking
pytest. The optional startup test verifies 227 registered names in both naming
modes. No live API writes are performed.
