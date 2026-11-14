# ISMS Consulting Copilot

An independent MCP/stdio server, not an official audatis extension. Start through
your MCP client using `copilot_server.py` and the virtual-environment interpreter.
It remains usable without the optional manufacturer contract.

## Seven tools

| Name | Purpose |
|---|---|
| `copilot_capabilities` | Explain local assessment rules and limitations |
| `assess_evidence` | Assess a supplied evidence bundle deterministically |
| `collect_assessment` | Preview collection; read only after both explicit consents |
| `plan_remediation` | Produce confirmation-required proposals; asset-only scope: at most three bundles |
| `render_consulting_report` | Render Markdown/HTML; asset-only scope defaults to a management summary |
| `load_portfolio_case` | Load the built-in synthetic runtime sample; legacy public name retained |
| `build_consulting_brief` | Prepare an evidence-bound, minimized assistant brief |

`sample_data.py` contains fictional literals required by the sample-loading tool
and regression tests. No application-portfolio presentation, generated reports
or external files are needed. The seven existing MCP names and assessment rules
are preserved.

## Evidence and responsibility

Results distinguish confirmed data observations, missing documentation and facts
that cannot be verified. Explicit `null` differs from an omitted field.
Scope, sources, object IDs, JSON pointers and checksums support traceability.
Checksums establish neither origin nor truth.

Recommendations are proposals, not assignments or automatic audatis writes.
The engine calls no AI service. A separately approved MCP client may process
outputs; review its recipient, processing location and permissions first.
API-sourced free text is untrusted data, never agent instructions.

Collection uses only the existing main server's allowlisted reading tools.
Both `allow_live_read` and `acknowledge_sensitive_output` are required; otherwise
the result is a local plan without API access. Main-server module and tenant
guards remain in force. Missing pages or inaccessible references remain explicit.

For the small three-asset offline sample, run `python -m isms_copilot demo`.
For your authorized local bundle, use
`python -m isms_copilot assess <BUNDLE_JSON>`.
Outputs may be sensitive; they are not repository assets and must not be committed.
The CLI writes `report.md`, `report.html` and `details.json` under the operator-defined
`AUDATIS_COPILOT_OUTPUT_DIR` (default: the repository's ignored `copilot-output/`).
`--output` may select a child directory, not escape this root. The root must be private
(0700); files use 0600. Existing different outputs require explicit `--overwrite`;
`--check` never writes. Symlink outputs are rejected. No automatic deletion is performed.
The tests generate their outputs in temporary directories. See the
[three-instruction live demo](ASSET_DEMO.md) for approval and partial-success handling.

For asset-only assessments, the short report shows at most six overview rows,
three grouped findings and three recommendations. It explicitly states any omitted
overview rows. The structured detail artifact retains every assessed asset, finding,
evidence pointer, source value and checksum. The full multi-resource renderer and
legacy synthetic sample remain available for existing callers and regression tests.

This is not a certification, legal assessment, vulnerability scanner or proof of
real security improvement. Professional review and actual control tests remain
necessary.
