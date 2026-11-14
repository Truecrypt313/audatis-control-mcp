# Three-instruction asset demo

Two MCP/stdio servers, existing tools only: audatisControl handles supported API
operations; the ISMS Consulting Copilot handles evidence and reports.
No new MCP tool or REST operation is added.

## Setup

Install both requirements files and configure an authorized non-production tenant
and least-privilege credentials as described in [PUBLIC_SETUP.md](PUBLIC_SETUP.md).
Set the main process to `AUDATIS_MCP_MODULES=core,assets` and
`AUDATIS_MCP_TOOL_NAMES=modern`. Restart both processes after configuration changes.

| Mode | Main `all` | Main `core,assets` | Separate Copilot |
|---|---:|---:|---:|
| No manufacturer specification | 48 | 20 | 7 |
| Reviewed authorized local specification | 227 | 24 | 7 |

The demo needs no manufacturer specification: all required API tools are in the
base integration. Module profiles are not read-only enforcement. The write-capable
main server still needs an approved tenant and a separate protected write credential.
The Copilot does not perform writes.

For file export, the operator defines a private local `AUDATIS_COPILOT_OUTPUT_DIR`.
The default is the ignored `copilot-output/` directory beside `server.py`.
Do not point this at a repository intended for publishing. The CLI rejects
escapes, symlinks and a pre-existing output root with group/world permissions.

## The three user instructions

### 1. Inventory

> Liste alle Assets vollständig auf. Berücksichtige sämtliche API-Seiten und
> kennzeichne Einschränkungen der Sichtbarkeit. Ändere nichts.

The client calls `list_assets(page=..., per_page=100)` until `meta.total_pages`
is exhausted. Do not infer a technical outage or missing risk assessment from
a status code or zero linked risks.

### 2. Plan, pause, confirm

> Bereite DEMO-FW-01, DEMO-SRV-01 und DEMO-WST-01 vor. Ermittle Kategorien und
> Typen aus den tatsächlichen Lookups, prüfe vorhandene Namen, zeige mir den
> vollständigen Erstellungsplan ohne Schreibzugriff und warte auf meine Freigabe.

Expected category/type choices, **not hardcoded IDs**:

| Name | Category label | Type label |
|---|---|---|
| DEMO-FW-01 | Netzwerk & Infrastruktur | Firewall |
| DEMO-SRV-01 | Systeme | Server |
| DEMO-WST-01 | Systeme | Client / Arbeitsplatz |

The client must:

1. Read the current visible asset inventory completely, not reuse a stale first page.
2. Call `list_asset_categories` and `list_asset_types(category_id=...)`.
3. Use the returned IDs and active category/type associations. Stop if labels are
   unavailable, inactive or ambiguous; never guess UUIDs or silently create categories.
4. Stop on an existing normalized demo title. Do not rename, reuse or delete objects
   automatically. Rights and archive visibility limit this check.
5. Show all three titles, category/type names and IDs, and the exact payload.
   Call `bulk_create_records(resource="assets", items_json=..., execute=false)`.
   This preview is local; it does not itself perform a server-side duplicate check.
6. **Pause for a separate explicit confirmation**, for example:
   “Ich gebe genau diesen angezeigten Plan zur Erstellung frei.”
7. Only then call the same bulk payload with `execute=true, check_existing=true`.
   The existing tool rechecks the paginated inventory before any write.

There are three work instructions, not a promise to suppress the mandatory
confirmation dialog. `execute=true` is a technical execution flag, not independent
proof that a human approved a plan; the MCP client must enforce the pause.

### 3. Assess and report

> Analysiere nur die tatsächlich bestätigten Asset-IDs aus der Erstellung:
> Inventarstatus, Archivierung, Verantwortlichkeit, CIA, Beschreibung und
> dokumentierte Zuordnungen. Ich erlaube dafür die lesende Erhebung und die
> Rückgabe der Ergebnisse an diesen Client. Gib höchstens drei priorisierte
> Handlungsempfehlungen und erzeuge „Asset Assessment – Management Summary“
> als Markdown und HTML im definierten lokalen Ausgabeordner. Keine weiteren
> API-Schreiboperationen.

The client keeps the actual bulk result (`completed`, confirmed `created` IDs,
and any `stopped_at_index`). It builds:

```json
{
  "name": "Confirmed demo creations",
  "object_ids": {"assets": ["ACTUAL_CONFIRMED_ID_FROM_BULK_RESULT"]}
}
```

The placeholder above is explanatory and must never be submitted literally.

- Call `collect_assessment` with `resources_json='["assets"]'`, the explicit scope,
  the current Europe/Berlin assessment date, `allow_live_read=true` and
  `acknowledge_sensitive_output=true`. Without both consents the tool only previews.
- The bridge reads `get_record` plus protection-level and status lookups, respecting
  the main profile. It does not automatically expand into disabled resource groups.
- `collect_assessment` returns a bundle and assessment. For a supplied local bundle,
  `assess_evidence` performs the same deterministic evaluation.
- Call `plan_remediation`, then `render_consulting_report`. The asset-only profile
  creates at most three work packages covering every finding exactly once.
- Status and archive flags are documented states, not evidence of actual uptime.
  Owner IDs remain in details; a status label requires the real lookup.

## Partial success and uncertainty

The bulk call is not transactional. A successful first creation can be followed by
a failed or uncertain second request. Stop; **never retry or roll back automatically**.
Assess only the IDs explicitly confirmed in `created`. If none are confirmed,
do not assess the whole inventory as a fallback. An uncertain request may have
created another record: inspect remote state before any separately authorized retry.
Record this limitation in the client response; the report covers confirmed IDs only.

## Local export

The seven MCP tools retain their signatures and return report content without file
side effects. A client with separately approved local file/command access can save
the returned bundle inside the configured private output root and invoke:

```bash
python -m isms_copilot assess <AUTHORIZED_BUNDLE_JSON> --output run-01
```

`run-01` is relative to `AUDATIS_COPILOT_OUTPUT_DIR`, not an arbitrary filesystem
destination. Choose a new child directory for each run. Do not bypass overwrite
protection. A client without local file tools can return HTML/Markdown but must not
claim to have saved a file.

The output contains only:

- `report.html` and `report.md`: bounded overview, at most three finding groups and
  three recommendations, plus explicit limitations.
- `details.json`: original evidence bundle, complete inventory/findings, proposal
  plan, selection metadata and checksums. Treat it as sensitive; do not publish it.

Three demo assets fit on one or two printable A4 pages. Larger inventories show
at most six rows, explicitly counted; full detail is preserved separately. Long
untrusted text is bounded and escaped, never interpreted as instructions or HTML.

## Reproducible offline fallback

```bash
python -m isms_copilot demo --output offline-demo
python -m isms_copilot demo --output offline-demo --check
python -m pytest -q
```

The small sample contains only the three demo assets and synthetic lookup values.
It makes no API calls. The tests exercise real MCP SDK registrations with synthetic
HTTP mocks, including the approval pause, lookup selection, pagination, duplicates,
partial success, confirmed-ID analysis, export containment and non-writing reports.

## Cleanup boundaries

The unused `apply_mcp_naming.py` migration script and the CLI's orphaned presentation
import have been retired. No runtime adapter, required safety mechanism, historical
release or license file is removed. The legacy multi-resource sample remains because
the existing `load_portfolio_case` tool and regression tests still use it.
No private local presentation, configuration or generated output is deleted.
