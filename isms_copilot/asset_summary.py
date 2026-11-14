"""Bounded, printable asset summary; full evidence stays in structured details."""
from __future__ import annotations

from .model import digest
from .planner import compact_asset_actions
from .report import STATUS_LABELS, esc, md

MAX_ROWS = 6
CSS = """
@page{size:A4;margin:13mm}
*{box-sizing:border-box}body{margin:0;color:#183348;background:#f3f6f7;font:14px/1.4 system-ui,sans-serif}
main{max-width:1000px;margin:24px auto;background:white;padding:30px;border-top:5px solid #006c68}
h1{font-size:27px;line-height:1.15;margin:0 0 14px}h2{font-size:17px;margin:20px 0 8px;color:#006c68}
p{margin:8px 0}.muted,footer{font-size:12px;color:#526777}.notice{padding:10px;background:#fff5df}
table{width:100%;border-collapse:collapse;table-layout:fixed;font-size:12px}
td,th{border:1px solid #d9e4e7;padding:7px;text-align:left;vertical-align:top;overflow-wrap:anywhere}
th{background:#edf5f3}ol{padding-left:22px}li{margin:9px 0;break-inside:avoid}
@media(max-width:600px){main{padding:16px;margin:0}h1{font-size:24px}td,th{padding:4px;font-size:11px}}
@media print{body{background:white;font-size:9.5pt}main{padding:0;margin:0;max-width:none;border-top:3px solid #006c68}
h1{font-size:20pt;margin-top:10px}h2{font-size:12pt;margin-top:13px}table{font-size:8.5pt}
td,th{padding:5px}tr,li{break-inside:avoid}h2{break-after:avoid}.muted,footer{font-size:8pt}}
"""


def short(value, limit=80):
    value = " ".join(str(value).split())
    return value if len(value) <= limit else value[:limit - 1] + "…"


def counted(number, singular, plural):
    return f"{number} " + (singular if number == 1 else plural)


def asset_cells(obj):
    details = obj.get("asset_details", {})
    archive = details.get("is_archived")
    archived = "ja" if archive is True else "nein" if archive is False else "unbekannt"
    owner = obj["primary_owner"]
    owner_label = "hinterlegt" if type(owner) is int and owner > 0 else "offen" if owner is None else "unbekannt"
    cia = details.get("cia_labels", {})
    cia_text = " / ".join(short(cia.get(d, "unbekannt"), 16)
                          for d in ("confidentiality", "integrity", "availability"))
    described = details.get("description_documented")
    description = "dokumentiert" if described is True else "offen" if described is False else "unbekannt"
    links = details.get("links", {})
    counts = " / ".join(str(links.get(k)) if type(links.get(k)) is int else "?"
                        for k in ("information_values", "measures", "linked_assets"))
    return [short(obj["label"], 42), short(details.get("status_label", "nicht überprüfbar"), 26)
            + " · archiviert: " + archived, owner_label, cia_text, description, counts]


def render_asset_summary(assessment: dict, plan: dict) -> dict:
    ctx, counts = assessment["context"], assessment["summary"]
    inventory = [obj for obj in assessment["inventory"] if obj["resource"] == "assets"]
    rows = inventory[:MAX_ROWS]
    recommendations = compact_asset_actions(plan["actions"], assessment)
    themes = {"governance": "Verantwortung/Status", "coverage": "Erhebungsumfang",
              "protection": "CIA-Schutzbedarf", "documentation": "Beschreibung",
              "relationships": "Zuordnungen", "duplicates": "Dublettenkandidaten"}
    findings = []
    for status in STATUS_LABELS:
        members = [f for f in assessment["findings"] if f["status"] == status]
        if members:
            topics = sorted({themes.get(f["topic"], "Dokumentationsstand") for f in members})
            findings.append({
                "priority": min(f["priority"] for f in members), "status": status,
                "text": counted(len(members), "Datenpunkt", "Datenpunkte") + ": " + short(", ".join(topics), 110)
                        + ". Einzelbelege im strukturierten Detailartefakt.",
                "finding_ids": [f["finding_id"] for f in members],
            })
    findings.sort(key=lambda f: (f["priority"], f["status"]))
    headline = "Asset Assessment – Management Summary"
    coverage = assessment["coverage"]["assets"]
    note = ("Synthetische Demonstration – keine realen Unternehmensdaten."
            if ctx["synthetic"] else "Vertraulich – autorisierter API-Sichtbestand.")
    summary = (counted(counts["assessed_records"], "Asset", "Assets") + " bewertet: "
               + counted(counts["by_status"]["confirmed_finding"], "belegter Datenbefund", "belegte Datenbefunde") + ", "
               + counted(counts["by_status"]["missing_documentation"], "Dokumentationslücke", "Dokumentationslücken") + ", "
               + counted(counts["by_status"]["not_verifiable"], "nicht überprüfbarer Datenpunkt", "nicht überprüfbare Datenpunkte") + ". "
               + counted(len(recommendations), "gebündelte Handlungsempfehlung", "gebündelte Handlungsempfehlungen")
               + "; keine automatische Umsetzung.")
    if not assessment["findings"]:
        summary += " Keine Regel ausgelöst; dies ist kein Konformitäts- oder Vollständigkeitsnachweis."
    scope = (f"Datum: {ctx['as_of']} (Europe/Berlin) · Organisation: {short(ctx['organisation'], 65)} · "
             f"Scope: {short(ctx['scope']['name'], 90)}")
    shown = f"Übersicht: {len(rows)} von {len(inventory)} bewerteten Assets gezeigt; vollständige Daten im Detailartefakt."
    limits = ("Inventarstatus ist kein Nachweis technischer Funktionsfähigkeit. "
              "Prioritäten betreffen Dokumentations- und Klärungsbedarf, keine bestätigten Schwachstellen. "
              "Keine technischen Kontrolltests oder ISO-27001-/NIS-2-Konformitätsprüfung.")
    scope_limit = ("Die beauftragte Auswahl ist im gelieferten Auszug belegt; kein atomarer Snapshot."
                   if coverage["scope_complete"] else
                   "Die beauftragte Auswahl ist nicht vollständig belegt; fehlende Sichtbarkeit und Erhebungsgrenzen bleiben offen.")
    md_lines = ["# " + headline, "", md(scope), "", "**" + md(note) + "**", "",
                "## 1. Zusammenfassung", "", md(summary), "",
                "## 2. Analysierte Assets", "", md(shown), "",
                "| Asset | Status / Archivierung | Owner | C / I / A | Beschreibung | I / M / A |",
                "|---|---|---|---|---|---|"]
    out = ['<!doctype html><html lang="de"><head><meta charset="utf-8">',
           '<meta name="viewport" content="width=device-width,initial-scale=1">',
           '<meta http-equiv="Content-Security-Policy" content="default-src \'none\'; style-src \'unsafe-inline\'; img-src \'none\'; base-uri \'none\'; form-action \'none\'">',
           "<title>" + headline + "</title><style>" + CSS + "</style></head><body><main>",
           "<h1>" + headline + "</h1><p>" + esc(scope) + "</p>",
           '<p class="notice">' + esc(note) + "</p>",
           "<h2>1. Zusammenfassung</h2><p>" + esc(summary) + "</p>",
           "<h2>2. Analysierte Assets</h2><p class=\"muted\">" + esc(shown) + "</p>",
           "<table><thead><tr>" + "".join("<th>" + c + "</th>" for c in
            ("Asset", "Status / Archiv", "Owner", "C / I / A", "Beschreibung", "I / M / A"))
           + "</tr></thead><tbody>"]
    for obj in rows:
        cells = asset_cells(obj)
        md_lines.append("| " + " | ".join(md(c) for c in cells) + " |")
        out.append("<tr>" + "".join("<td>" + esc(c) + "</td>" for c in cells) + "</tr>")
    legend = "Zuordnungen I/M/A: Informationswerte / Maßnahmen / Asset-Bezüge; ? = unbekannt. Leer bedeutet nicht, dass reale Kontrollen fehlen."
    md_lines += ["", md(legend), "", "## 3. Wesentliche Befunde", ""]
    out += ["</tbody></table><p class=\"muted\">" + esc(legend) + "</p>",
            "<h2>3. Wesentliche Befunde</h2><ul>"]
    for finding in findings:
        line = finding["priority"] + " · " + STATUS_LABELS[finding["status"]] + ": " + finding["text"]
        md_lines.append("- " + md(line))
        out.append('<li class="finding">' + esc(line) + "</li>")
    if not findings:
        md_lines.append("Keine wesentlichen Dokumentationsbefunde aus den angewandten Regeln.")
        out.append("<li>Keine wesentlichen Dokumentationsbefunde aus den angewandten Regeln.</li>")
    md_lines += ["", "## 4. Handlungsempfehlungen", ""]
    out += ["</ul><h2>4. Handlungsempfehlungen</h2><ol>"]
    for number, action in enumerate(recommendations, 1):
        title = action["priority"] + " · " + short(action["title"], 75)
        body = short(action["recommendation"], 190)
        md_lines += [f"{number}. **{md(title)}** – {md(body)}"]
        out.append('<li class="recommendation"><strong>' + esc(title) + "</strong> – " + esc(body) + "</li>")
    if not recommendations:
        md_lines.append("Keine zusätzlichen Maßnahmen aus den angewandten Regeln abgeleitet.")
        out.append("<li>Keine zusätzlichen Maßnahmen aus den angewandten Regeln abgeleitet.</li>")
    approval = "Owner, Nachweise und vorgeschlagene Termine sind fachlich zu bestätigen; Details und vollständige Befunde stehen im separaten strukturierten Artefakt."
    md_lines += ["", md(approval), "", "## 5. Untersuchungsgrenzen", "", md(scope_limit), "", md(limits), ""]
    out += ["</ol><p class=\"muted\">" + esc(approval) + "</p>",
            "<h2>5. Untersuchungsgrenzen</h2><p>" + esc(scope_limit) + "</p><p>" + esc(limits) + "</p>",
            "<footer>ISMS Consulting Copilot · unabhängiges Projekt, kein offizielles audatis-Produkt.</footer></main></body></html>"]
    markdown, html = "\n".join(md_lines), "\n".join(out)
    return {"markdown": markdown, "html": html, "report_sha256": digest({"markdown": markdown, "html": html}),
            "will_write": False, "sensitive_output": not ctx["synthetic"],
            "format": "asset-management-summary",
            "technical_details": {"assessment": assessment, "plan": plan,
                                  "displayed_asset_ids": [obj["object_id"] for obj in rows],
                                  "finding_groups": findings, "recommendations": recommendations}}
