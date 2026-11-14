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
| `plan_remediation` | Produce confirmation-required remediation proposals |
| `render_consulting_report` | Render Markdown and escaped HTML |
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

For an offline sample, run `python -m isms_copilot demo --output <LOCAL_OUTPUT>`.
For your authorized local bundle, use
`python -m isms_copilot assess <BUNDLE_JSON> --output <LOCAL_OUTPUT>`.
Outputs may be sensitive; they are not repository assets and must not be committed.
The tests generate their outputs in temporary directories.

This is not a certification, legal assessment, vulnerability scanner or proof of
real security improvement. Professional review and actual control tests remain
necessary.
