# Security and distribution boundaries

## Included

Project implementation, independently written tests, synthetic runtime data and
technical documentation. The small public loader fixture tests two operations;
it is not a replacement for the manufacturer's catalog. Validation-only legacy
contracts retain functional field constraints; vendor examples and descriptive
annotations must not be included in an export.

## Excluded

- Manufacturer OpenAPI files, including `specs/`, and complete generated equivalents.
- API-derived coverage/backlog matrices, generated tool documentation and private
  documentation-generation scripts.
- `.env`, tokens, private keys, tenant/customer exports, local MCP configurations,
  personal paths and operational logs.
- Application portfolio directories, documents, presentations, generated reports
  and portfolio-only tests/builders.

The full contract remains a privately supplied runtime prerequisite for extended
mode. No vendor redistribution right is claimed by the software license.
Functional interoperability constraints are not a substitute API specification.

## Operational safeguards

Use a dedicated authorized tenant, least-privilege read credentials and a
separate protected write credential. Require positive, aligned tenant settings
in the public distribution. Tool profiles are not read-only enforcement.
Legacy immediate-write tools do not gain preview protection retroactively.

Management mutations require explicit execution; incident changes and deletions
require additional acknowledgements. Some operations may notify people or affect
linked records. There is no transactional rollback or automatic retry. A network
error may leave an uncertain remote state: inspect it before repeating a write.
Do not log credentials or full response payloads.

## Publication checks

Review an explicit export allowlist, staged filenames and the actual staged diff.
Check secrets and identifiers without printing sensitive values. Test a clean
export without a vendor file, plus a private offline run with the authorized
contract. Confirm legacy names/signatures and all seven Copilot tools.

Keep `LICENSE.md`, `NOTICE` and `COMMERCIAL-LICENSING.md` unchanged. A technical
preflight is not a legal opinion or an absolute guarantee that no secret exists.
The local development repository and old public history are not merged or rewritten.
