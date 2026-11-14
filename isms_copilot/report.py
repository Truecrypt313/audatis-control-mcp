"""Professional dual rendering; no raw HTML/Markdown, remote assets or JS from data."""
from __future__ import annotations

import html
import json

from .model import RESOURCES, assets_only, digest
from .planner import plan_remediation, validate_assessment, validate_plan

STATUS_LABELS = {
    "confirmed_finding": "Bestätigter Datenbefund",
    "missing_documentation": "Fehlende Dokumentation",
    "not_verifiable": "Nicht überprüfbar",
}
CSS = """
:root{color-scheme:light;--navy:#163047;--teal:#006b70;--line:#d8e1e7}
body{font:15px/1.55 system-ui,sans-serif;color:#203544;margin:0;background:#eef2f5}
main{max-width:1120px;margin:32px auto;background:white;padding:44px;border-top:8px solid var(--teal)}
h1,h2,h3{color:var(--navy);line-height:1.25}h1{font-size:36px}h2{margin-top:38px;border-bottom:2px solid var(--line);padding-bottom:8px}
.eyebrow{color:var(--teal);text-transform:uppercase;letter-spacing:.1em;font-weight:700}.notice{background:#fff3d7;border-left:4px solid #a86c00;padding:14px}
.metrics{display:flex;gap:16px;flex-wrap:wrap}.metric{background:#edf5f5;padding:16px;min-width:150px}.metric strong{display:block;font-size:28px}
table{border-collapse:collapse;width:100%;margin:16px 0;font-size:13px}th,td{padding:9px;vertical-align:top;border:1px solid var(--line);overflow-wrap:anywhere}th{background:#edf2f6;text-align:left}
article{border:1px solid var(--line);border-left:4px solid var(--teal);padding:16px;margin:18px 0}
.muted,footer{color:#526879;font-size:12px}.priority{font-weight:700}code{font-size:12px;overflow-wrap:anywhere}
@media print{body{background:white}main{margin:0;padding:12px;max-width:none}h2,h3{break-after:avoid}article{break-inside:avoid}a{color:inherit}}
"""


def text(value) -> str:
    if isinstance(value, (dict, list)):
        return json.dumps(value, ensure_ascii=False, sort_keys=True)
    return "null" if value is None else str(value)


def esc(value) -> str:
    return html.escape(text(value), quote=True)


def md(value) -> str:
    value = html.escape(text(value), quote=True).replace("\r", " ").replace("\n", " / ")
    for char in "\\`*_{}[]()#+!|":
        value = value.replace(char, "\\" + char)
    return value


def render_report(assessment: dict, plan: dict | None = None) -> dict:
    validate_assessment(assessment)
    plan = plan_remediation(assessment) if plan is None else plan
    validate_plan(plan, assessment)
    if assets_only(assessment):
        from .asset_summary import render_asset_summary
        return render_asset_summary(assessment, plan)
    ctx, summary = assessment["context"], assessment["summary"]
    synthetic = ctx["synthetic"]
    notice = ("FIKTIVES PORTFOLIO-SZENARIO – ausschließlich synthetische Daten. Keine Aussage über ein reales Unternehmen."
              if synthetic else "VERTRAULICH – autorisierter API-Sichtbestand. Weitergabe und KI-Verarbeitung gesondert freigeben.")
    executive = (
        f"{summary['assessed_records']} Objekte im beauftragten Scope ausgewertet. "
        f"{summary['by_status']['confirmed_finding']} bestätigte Datenbefunde, "
        f"{summary['by_status']['missing_documentation']} Dokumentationslücken und "
        f"{summary['by_status']['not_verifiable']} nicht überprüfbare Sachverhalte. "
        f"{len(plan['actions'])} gebündelte Maßnahmenvorschläge; keine automatische Umsetzung."
    )
    if not assessment["findings"]:
        executive += " Keine Regel ausgelöst; dies ist weder ein Vollständigkeits- noch ein Konformitätsnachweis."
    intro = [
        "# ISMS Consulting Assessment", "", f"## {md(ctx['organisation'])}", "",
        f"**{md(notice)}**", "",
        f"Stichtag (Europe/Berlin): {md(ctx['as_of'])} · Erfassung: {md(ctx['captured_at'])} · Scope: {md(ctx['scope']['name'])}",
        f"Assessment: `{assessment['assessment_id']}` · Regeln: `{md(assessment['ruleset_version'])}`", "",
        "## 1. Executive Summary", "", md(executive), "",
        "Empfehlung: P1-Punkte zuerst im Fachgespräch validieren, Zuständigkeiten klären und Evidenz nachfordern. "
        "Danach Schutzbedarf, Zuordnungen und Wirksamkeitsnachweise fachlich vervollständigen.", "",
        "**Keine automatische ISO-27001-/NIS-2-Konformitätsbewertung. Dokumentationspriorität ist keine Schwachstellenschwere.**", "",
        "## 2. Untersuchungsumfang", "",
        "Beauftragte Objekte werden getrennt von zur Referenzauflösung mitgelieferten Abhängigkeiten bewertet. "
        "Die Scope-Auswahl ist keine Datenzugriffsberechtigung.", "",
        "| Fachbereich | API-Bestand | Sichtbare Objekte | Bewertete Objekte | Im Scope | Primär-Auswahl belegt | Einschränkung |",
        "|---|---|---:|---:|---|---|---|",
    ]
    h = [
        '<!doctype html><html lang="de"><head><meta charset="utf-8">',
        '<meta name="viewport" content="width=device-width,initial-scale=1">',
        '<meta http-equiv="Content-Security-Policy" content="default-src \'none\'; style-src \'unsafe-inline\'; img-src \'none\'; base-uri \'none\'; form-action \'none\'">',
        "<title>ISMS Consulting Assessment</title><style>" + CSS + "</style></head><body><main>",
        '<p class="eyebrow">ISMS Consulting Copilot · Evidence first</p>',
        "<h1>ISMS Consulting Assessment</h1><h2>" + esc(ctx["organisation"]) + "</h2>",
        '<p class="notice">' + esc(notice) + "</p>",
        "<p>Stichtag (Europe/Berlin): " + esc(ctx["as_of"]) + " · Erfassung: " + esc(ctx["captured_at"])
        + "<br>Scope: " + esc(ctx["scope"]["name"]) + " · " + esc(assessment["assessment_id"]) + "</p>",
        "<h2>1. Executive Summary</h2><p>" + esc(executive) + "</p>",
        '<div class="metrics">' + "".join('<div class="metric"><strong>' + str(summary["by_status"][s])
                                         + "</strong>" + label + "</div>" for s, label in STATUS_LABELS.items()) + "</div>",
        "<p>P1-Punkte zuerst mit dem Fachbereich validieren; danach Schutzbedarf, Zuordnungen und Wirksamkeitsnachweise vervollständigen.</p>",
        '<p class="notice">Keine automatische ISO-27001-/NIS-2-Konformitätsbewertung. Dokumentationspriorität ist keine Schwachstellenschwere.</p>',
        "<h2>2. Untersuchungsumfang</h2><p>Primärobjekte und Abhängigkeiten werden getrennt betrachtet; Scope ist keine Zugriffsberechtigung.</p>",
        "<table><thead><tr><th>Fachbereich</th><th>API-Bestand</th><th>Sichtbar</th><th>Bewertet</th><th>Im Scope</th><th>Primär-Auswahl belegt</th><th>Einschränkung</th></tr></thead><tbody>",
    ]
    for resource in RESOURCES:
        info = assessment["coverage"][resource]
        cells = [resource, info["state"], info["visible_records"], info["assessed_records"], info["in_scope"], info["scope_complete"], info["reason"]]
        intro.append("| " + " | ".join(md(c) for c in cells) + " |")
        h.append("<tr>" + "".join("<td>" + esc(c) + "</td>" for c in cells) + "</tr>")
    method = (
        "Lokale deterministische Regeln auf einem datierten Evidence-Bundle; keine aktive Discovery. "
        "Explizit leere Felder und nicht gelieferte Felder werden unterschiedlich bewertet. "
        "Quellen- und Bundle-Prüfsummen, Objekt-IDs und JSON-Pointer machen die Bewertung reproduzierbar. "
        "Unauflösbare Referenzen und Titeldubletten bleiben Prüfkandidaten. API-Werte sind nicht extern verifiziert."
    )
    intro += ["", "## 3. Methodik", "", method, "",
              "## 4. IST-Zustand", "",
              "Die Tabelle oben beschreibt ausschließlich den gelieferten Sichtbestand. "
              "Der Befundkatalog unten konkretisiert dokumentierte Verantwortlichkeit, Schutzbedarf, "
              "Prozessinhalte, Bewertungswerte, Zuordnungen, Reviews und Maßnahmenstände.", "",
              "Schutzbedarf und Risikowerte sind gespeicherte Codes/Werte, keine neu berechnete Einstufung. "
              "Ohne gültige Stufenliste bzw. Bewertungsmatrix keine weitergehende Interpretation.", "",
              "| Fachbereich / Objekt-ID | Bezeichnung | Primär-Owner (ID) | CIA / Status / Risikowerte | Quelle / SHA-256 |",
              "|---|---|---|---|---|"]
    h += ["</tbody></table><h2>3. Methodik</h2><p>" + esc(method) + "</p>",
          "<h2>4. IST-Zustand</h2><p>Der gelieferte Sichtbestand bildet die Basis für die nachfolgenden, belegbezogenen Einzelbewertungen.</p>",
          "<p>Schutzbedarf/Risikowerte sind gespeicherte Werte, keine neu berechneten Einstufungen. Bewertungsmethodik separat prüfen.</p>",
          "<table><tr><th>Fachbereich / Objekt-ID</th><th>Bezeichnung</th><th>Primär-Owner (ID)</th><th>CIA / Status / Risikowerte</th><th>Quelle / SHA-256</th></tr>"]
    for obj in assessment["inventory"]:
        cells = [obj["resource"] + " / " + obj["object_id"], obj["label"], obj["primary_owner"],
                 {"CIA": obj["protection"], "status": obj["status"], "risk_values": obj["risk_values"]},
                 obj["source_id"] + " / " + obj["data_sha256"]]
        intro.append("| " + " | ".join(md(cell) for cell in cells) + " |")
        h.append("<tr>" + "".join("<td>" + esc(cell) + "</td>" for cell in cells) + "</tr>")
    intro += ["", "## 5. Befunde und Evidenz", ""]
    h.append("</table><h2>5. Befunde und Evidenz</h2>")
    for finding in assessment["findings"]:
        label = STATUS_LABELS[finding["status"]]
        intro += [f"### {md(finding['finding_id'])} · {finding['priority']} · {md(finding['title'])}", "",
                  f"- Bewertung: **{label}**",
                  f"- Objekt: {md(finding['resource'])} / {md(finding['object_id'])}",
                  f"- Begründung: {md(finding['rationale'])}",
                  f"- Priorisierung: {md(finding['priority_basis'])}", "",
                  "| Quelle / Tool | Objekt-ID | Feld / JSON-Pointer | Geliefert | Beobachtung | Quellen-SHA-256 |",
                  "|---|---|---|---|---|---|"]
        h += ["<article><h3>" + esc(finding["finding_id"]) + " · " + esc(finding["priority"]) + " · " + esc(finding["title"]) + "</h3>",
              "<p><strong>" + esc(label) + "</strong> · " + esc(finding["resource"]) + " / " + esc(finding["object_id"]) + "</p>",
              "<p>" + esc(finding["rationale"]) + "</p><p class=\"muted\">" + esc(finding["priority_basis"]) + "</p>",
              "<table><tr><th>Quelle / Tool</th><th>Objekt-ID</th><th>Feld / Pointer</th><th>Geliefert</th><th>Beobachtung</th><th>Quellen-SHA-256</th></tr>"]
        for ev in finding["evidence"]:
            cells = [f"{ev['source_id'] or 'Bundle'} / {ev['tool']}", ev["object_id"],
                     f"{ev['field']} / {ev['pointer']}", ev["present"], ev["observed"], ev["data_sha256"]]
            intro.append("| " + " | ".join(md(c) for c in cells) + " |")
            h.append("<tr>" + "".join("<td>" + esc(c) + "</td>" for c in cells) + "</tr>")
        intro.append("")
        h.append("</table></article>")
    intro += ["## 6. Empfehlungen und Priorisierungsmodell", ""]
    h.append("<h2>6. Empfehlungen und Priorisierungsmodell</h2>")
    for priority, criterion in assessment["priority_criteria"].items():
        description = f"{priority}: {criterion['criterion']}. Fristvorschlag: {criterion['days']} Kalendertage."
        intro += ["- " + md(description)]
        h.append("<p><strong>" + esc(priority) + "</strong>: " + esc(description) + "</p>")
    intro += ["", "## 7. Maßnahmenplan – ausschließlich Vorschläge", "",
              "Keine audatisManager-Daten wurden angelegt oder geändert. Owner, Termine und Akzeptanz sind fachlich zu bestätigen.", "",
              "| Maßnahme / Befunde | Priorität | Empfehlung | Verantwortlichkeitsvorschlag | Fristvorschlag | Nachweise / Abnahme |",
              "|---|---|---|---|---|---|"]
    h += ["<h2>7. Maßnahmenplan – ausschließlich Vorschläge</h2><p>Keine automatische Anlage oder Zuweisung. Owner und Fristen sind zu bestätigen.</p>",
          "<table><tr><th>Maßnahme / Befunde</th><th>Priorität</th><th>Empfehlung</th><th>Owner-Vorschlag</th><th>Termin</th><th>Nachweise / Abnahme</th></tr>"]
    for action in plan["actions"]:
        owner = action["owner_proposal"]
        cells = [
            action["action_id"] + " / " + ", ".join(action["finding_ids"]), action["priority"],
            action["title"] + ": " + action["recommendation"],
            f"{owner['role']} / ID {owner['user_id'] or 'offen'}; Bestätigung erforderlich",
            action["due_date_proposal"] + " / " + action["due_basis"],
            "; ".join(action["evidence_requirements"]) + " / " + action["acceptance"],
        ]
        intro.append("| " + " | ".join(md(c) for c in cells) + " |")
        h.append("<tr>" + "".join("<td>" + esc(c) + "</td>" for c in cells) + "</tr>")
    intro += ["", "## 8. Einschränkungen und offene Nachweise", ""]
    h.append("</table><h2>8. Einschränkungen und offene Nachweise</h2><ul>")
    for limitation in assessment["limitations"] + plan["limitations"]:
        intro.append("- " + md(limitation))
        h.append("<li>" + esc(limitation) + "</li>")
    intro += ["", "## 9. Reproduzierbarkeit und Review", "",
              f"- Bundle-SHA-256: `{assessment['bundle_sha256']}`",
              f"- Assessment-SHA-256: `{assessment['assessment_sha256']}`",
              f"- Plan-SHA-256: `{plan['plan_sha256']}`",
              "- Erforderliche menschliche Freigabe: Scope, Evidenz, Priorisierung, Owner und Fristen.",
              "- Eigenständiges Portfolio-Projekt; kein offizielles Produkt und keine Zertifizierung von audatis.", ""]
    h += ["</ul><h2>9. Reproduzierbarkeit und Review</h2>",
          "<p>Bundle: <code>" + esc(assessment["bundle_sha256"]) + "</code><br>Assessment: <code>" + esc(assessment["assessment_sha256"])
          + "</code><br>Plan: <code>" + esc(plan["plan_sha256"]) + "</code></p>",
          "<footer>Eigenständiges Portfolio-Projekt, kein offizielles Produkt von audatis. "
          "Menschlicher Review und Freigabe von Scope, Evidenz, Prioritäten, Ownern und Fristen erforderlich.</footer></main></body></html>"]
    markdown, html_report = "\n".join(intro), "\n".join(h)
    return {"markdown": markdown, "html": html_report,
            "report_sha256": digest({"markdown": markdown, "html": html_report}),
            "will_write": False, "sensitive_output": not synthetic}
