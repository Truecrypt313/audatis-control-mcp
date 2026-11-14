"""Proposal-only remediation: no audatis mutation, assignment, or notification."""
from __future__ import annotations

from collections import defaultdict
from datetime import date, timedelta

from .assessment import ASSET_RULESET_VERSION, PRIORITIES, RULESET_VERSION
from .model import BUNDLE_SCHEMA, ID, RESOURCES, STATUSES, assets_only, digest, seal, validate, verify_seal

STRING = {"type": "string", "maxLength": 20000}
HASH = {"type": "string", "pattern": "^[0-9a-f]{64}$"}
NULL_ID = {"anyOf": [ID, {"type": "null"}]}
EVIDENCE_SCHEMA = {
    "type": "object", "additionalProperties": False,
    "required": ["source_id", "tool", "object_id", "field", "pointer", "present", "observed", "data_sha256"],
    "properties": {"source_id": NULL_ID, "tool": ID, "object_id": NULL_ID,
                   "field": STRING, "pointer": STRING, "present": {"type": "boolean"},
                   "observed": {}, "data_sha256": HASH},
}
FINDING_SCHEMA = {
    "type": "object", "additionalProperties": False,
    "required": ["finding_id", "rule_id", "status", "priority", "priority_basis", "resource",
                 "object_id", "title", "rationale", "topic", "evidence", "accountable_user_id"],
    "properties": {
        "finding_id": {"type": "string", "pattern": "^F-[0-9a-f]{16}$"},
        "rule_id": ID, "priority": {"enum": list(PRIORITIES)}, "status": {"enum": list(STATUSES)},
        "resource": {"enum": list(RESOURCES)}, "object_id": NULL_ID,
        "priority_basis": STRING, "title": STRING, "rationale": STRING,
        "topic": ID, "evidence": {"type": "array", "minItems": 1, "maxItems": 2000, "items": EVIDENCE_SCHEMA},
        "accountable_user_id": {"anyOf": [{"type": "integer", "minimum": 1}, {"type": "null"}]},
    },
}

TEMPLATES = {
    "coverage": ("Untersuchungsumfang und Evidenz vervollständigen", "Datenzugriff/Scope mit Auftraggeber klären; fehlende Auszüge oder Nachweise gezielt nachfordern.",
                 ["Bestätigter Untersuchungsumfang", "Vollständiger autorisierter Auszug oder dokumentierte Einschränkung"]),
    "governance": ("Verantwortlichkeit verbindlich klären", "Fachlich verantwortliche Rolle benennen und die Zuordnung nach Freigabe dokumentieren.",
                   ["Bestätigte Zuständigkeit/RACI", "Freigabe der betroffenen Rolle und dokumentierte Zuordnung"]),
    "protection": ("Schutzbedarf nachvollziehbar begründen", "C/I/A im Fachinterview bewerten; Begründung, Datenabhängigkeiten und Freigabe festhalten.",
                   ["Begründete C/I/A-Bewertung", "Freigabe durch fachlichen Owner", "Nachvollziehbare Vererbungsquelle, falls verwendet"]),
    "documentation": ("Fachliche Dokumentation ergänzen", "Zweck, Geltungsbereich und Abläufe mit dem Fachbereich konkretisieren; Nichtanwendbarkeit begründen.",
                      ["Fachlich geprüfte Beschreibung", "Owner-Freigabe und Reviewdatum"]),
    "relationships": ("Zuordnungen und Referenzen validieren", "Abhängigkeiten fachlich bestätigen; Sichtbarkeit/Archivierung prüfen. Nur dokumentierte API-Funktionen oder autorisierte UI-Pflege verwenden.",
                      ["Bestätigte Abhängigkeits-/Zuordnungsmatrix", "Aufgelöste Referenz oder begründete Nichtanwendbarkeit"]),
    "review": ("Review durchführen und Folgeprüfung planen", "Gespeicherten Reviewstand mit dem Owner abgleichen und Ergebnis sowie nächsten Termin dokumentieren.",
               ["Datiertes Reviewprotokoll", "Prüfer, Ergebnis und nächster freigegebener Termin"]),
    "delivery": ("Aufgabenstand und Frist abstimmen", "Status mit dem Bearbeiter abgleichen; ursprüngliche Frist nicht stillschweigend ersetzen und Erledigung nachweisen.",
                 ["Bearbeitungs-/Ergebnisnachweis", "Bestätigte Zuständigkeit und abgestimmter Termin"]),
    "verification": ("Umsetzung und Wirksamkeitsnachweis klären", "Geplante Umsetzung abstimmen; angemessenen Wirksamkeitstest definieren und separat durchführen lassen.",
                     ["Umsetzungsnachweis", "Testprotokoll mit Datum, Ergebnis und Prüfer", "Freigabe oder dokumentierte Restunsicherheit"]),
    "valuation": ("Bewertungsgrundlage vervollständigen", "Risikomethodik und Bewertungsmatrix beschaffen; Werte und Begründungen mit dem Owner dokumentieren, nicht automatisch errechnen.",
                  ["Freigegebene Bewertungsmethodik", "Begründete Brutto-/Nettobewertung", "Fachliche Freigabe"]),
    "duplicates": ("Dublettenkandidaten fachlich vergleichen", "Identifikatoren und Geltungsbereiche vergleichen; keine automatische Zusammenführung oder Löschung.",
                   ["Dokumentierter Objektvergleich", "Entscheidung: getrennte Objekte oder freigegebene Bereinigung"]),
}
ROLE_DEFAULTS = {
    "assets": "IT-Assetverantwortung", "information-values": "Fachliche Informationsverantwortung",
    "business-processes": "Prozessverantwortung", "measures": "Maßnahmenverantwortung",
    "risks": "ISMS-/Risikokoordination", "tasks": "Teamleitung",
}


def validate_assessment(assessment: dict) -> None:
    verify_seal(assessment, "assessment_sha256")
    validate({
        "type": "object", "additionalProperties": False,
        "required": ["schema_version", "engine_version", "ruleset_version", "assessment_id", "bundle_sha256",
                     "context", "findings", "coverage", "summary", "limitations", "priority_criteria",
                     "compliance_conclusion", "assessment_sha256", "inventory"],
        "properties": {
            "schema_version": {"const": "1.0"}, "engine_version": ID,
            "ruleset_version": {"enum": [RULESET_VERSION, ASSET_RULESET_VERSION]}, "bundle_sha256": HASH, "assessment_sha256": HASH,
            "assessment_id": {"type": "string", "pattern": "^ASM-[0-9a-f]{20}$"},
            "context": BUNDLE_SCHEMA["properties"]["context"],
            "findings": {"type": "array", "maxItems": 20000, "items": FINDING_SCHEMA},
            "inventory": {"type": "array", "maxItems": 1000, "items": {
                "type": "object", "required": ["resource", "object_id", "label", "primary_owner", "protection", "status", "risk_values", "source_id", "data_sha256"],
                "properties": {"resource": {"enum": list(RESOURCES)}, "object_id": ID,
                               "source_id": ID, "data_sha256": HASH, "protection": {"type": "object"},
                               "risk_values": {"type": "object"}},
            }},
            "summary": {
                "type": "object", "additionalProperties": False,
                "required": ["findings", "assessed_records", "by_status", "by_priority"],
                "properties": {
                    "findings": {"type": "integer", "minimum": 0}, "assessed_records": {"type": "integer", "minimum": 0},
                    "by_status": {"type": "object", "required": list(STATUSES), "additionalProperties": False,
                                  "properties": {s: {"type": "integer", "minimum": 0} for s in STATUSES}},
                    "by_priority": {"type": "object", "required": list(PRIORITIES), "additionalProperties": False,
                                    "properties": {p: {"type": "integer", "minimum": 0} for p in PRIORITIES}},
                },
            },
            "coverage": {"type": "object", "required": list(RESOURCES), "additionalProperties": False,
                         "properties": {r: {
                             "type": "object", "required": ["state", "visible_records", "assessed_records", "in_scope", "scope_complete", "reason"],
                             "properties": {"state": {"enum": ["complete", "partial", "unavailable", "not_requested"]},
                                            "visible_records": {"type": "integer", "minimum": 0},
                                            "assessed_records": {"type": "integer", "minimum": 0},
                                            "in_scope": {"type": "boolean"}, "scope_complete": {"type": "boolean"}, "reason": STRING},
                         } for r in RESOURCES}},
            "limitations": {"type": "array", "items": STRING}, "priority_criteria": {"const": PRIORITIES},
            "compliance_conclusion": {"const": "not_assessed"},
        },
    }, assessment)
    ids = [f["finding_id"] for f in assessment["findings"]]
    if len(ids) != len(set(ids)):
        raise ValueError("Doppelte Befund-ID")
    if assessment["summary"]["findings"] != len(ids):
        raise ValueError("Befundsumme widersprüchlich")
    for key in ("status", "priority"):
        for value, count in assessment["summary"]["by_" + key].items():
            if count != sum(f[key] == value for f in assessment["findings"]):
                raise ValueError("Befundstatistik widersprüchlich")
    if any(f["topic"] not in TEMPLATES for f in assessment["findings"]):
        raise ValueError("Unbekanntes Maßnahmen-Thema")


def plan_remediation(assessment: dict, roles: dict | None = None) -> dict:
    validate_assessment(assessment)
    roles = roles if roles is not None else {}
    validate({"type": "object", "additionalProperties": False,
              "properties": {r: {"type": "string", "minLength": 1, "maxLength": 160} for r in RESOURCES}}, roles)
    grouped = defaultdict(list)
    for finding in assessment["findings"]:
        grouped[(finding["resource"], finding["object_id"], finding["topic"])].append(finding)
    actions = []
    for (resource, obj_id, topic), findings in sorted(grouped.items(), key=lambda item: str(item[0])):
        title, recommendation, requirements = TEMPLATES[topic]
        priority = min(f["priority"] for f in findings)
        owner_ids = {f["accountable_user_id"] for f in findings if f["accountable_user_id"] is not None}
        owner_id = next(iter(owner_ids)) if len(owner_ids) == 1 else None
        try:
            due_date = (date.fromisoformat(assessment["context"]["as_of"]) + timedelta(days=PRIORITIES[priority]["days"])).isoformat()
        except OverflowError:
            raise ValueError("Fristvorschlag außerhalb des darstellbaren Datumsbereichs") from None
        actions.append({
            "action_id": "A-" + digest([assessment["assessment_id"], resource, obj_id, topic])[:16],
            "finding_ids": sorted(f["finding_id"] for f in findings), "resource": resource,
            "object_id": obj_id, "topic": topic, "priority": priority, "title": title,
            "recommendation": recommendation,
            "owner_proposal": {"state": "existing_id_to_confirm" if owner_id else "role_proposal",
                               "user_id": owner_id, "role": roles.get(resource, ROLE_DEFAULTS[resource]),
                               "requires_confirmation": True},
            "due_date_proposal": due_date,
            "due_basis": f"{PRIORITIES[priority]['days']} Kalendertage ab Bewertungsstichtag; Vorschlag, keine gesetzliche Frist.",
            "priority_basis": PRIORITIES[priority]["criterion"],
            "evidence_requirements": requirements,
            "acceptance": "Nachweise fachlich prüfen und Freigabe dokumentieren; Status nicht automatisch als behoben markieren.",
            "status": "proposal", "will_write": False,
        })
    actions.sort(key=lambda action: (action["priority"], action["resource"], action["action_id"]))
    if assets_only(assessment):
        actions = compact_asset_actions(actions, assessment)
    return seal({
        "schema_version": "1.0", "assessment_id": assessment["assessment_id"],
        "assessment_sha256": assessment["assessment_sha256"], "mode": "proposal_only",
        "requires_human_approval": True, "will_write": False, "actions": actions,
        "limitations": ["Kein Task oder Maßnahmendatensatz wurde angelegt; Owner und Termine sind zu bestätigende Vorschläge.",
                        "Gesetzliche Meldefristen und technische Kritikalität werden nicht aus Dokumentationsprioritäten abgeleitet."],
    }, "plan_sha256")


def compact_asset_actions(actions: list[dict], assessment: dict) -> list[dict]:
    """At most three work packages; every original finding remains referenced once."""
    groups = defaultdict(list)
    for action in actions:
        key = ("governance" if action["topic"] in ("governance", "coverage")
               else "protection" if action["topic"] == "protection" else "documentation")
        groups[key].append(action)
    texts = {
        "governance": ("Verantwortung und Datenstand bestätigen",
                       "Betroffene Zuständigkeiten, Status-/Archivangaben und offene Erhebungspunkte fachlich bestätigen; fehlende Belege nachfordern."),
        "protection": ("CIA-Schutzbedarf begründen",
                       "Vertraulichkeit, Integrität und Verfügbarkeit der betroffenen Assets mit dem fachlichen Owner begründen und freigeben."),
        "documentation": ("Beschreibung und Zuordnungen vervollständigen",
                          "Betroffene Beschreibungen und dokumentierte Beziehungen prüfen; fehlende Angaben ergänzen oder Nichtanwendbarkeit begründen."),
    }
    result = []
    for topic, members in sorted(groups.items()):
        first = min(members, key=lambda a: (a["priority"], a["action_id"]))
        action = dict(first)
        title, recommendation = texts[topic]
        users = {m["owner_proposal"]["user_id"] for m in members}
        owner = dict(first["owner_proposal"])
        owner["user_id"] = next(iter(users)) if len(users) == 1 else None
        owner["state"] = "existing_id_to_confirm" if owner["user_id"] else "role_proposal"
        action.update({
            "action_id": "A-" + digest([assessment["assessment_id"], "asset-summary", topic])[:16],
            "object_id": None, "topic": topic, "title": title, "recommendation": recommendation,
            "object_ids": sorted({obj for m in members for obj in m.get("object_ids", [m.get("object_id")]) if obj}),
            "finding_ids": sorted({fid for m in members for fid in m["finding_ids"]}),
            "owner_proposal": owner,
            "evidence_requirements": sorted({e for m in members for e in m["evidence_requirements"]}),
        })
        result.append(action)
    return sorted(result, key=lambda a: (a["priority"], a["action_id"]))


def validate_plan(plan: dict, assessment: dict) -> None:
    verify_seal(plan, "plan_sha256")
    validate({
        "type": "object", "required": ["assessment_id", "assessment_sha256", "mode", "will_write",
                                     "requires_human_approval", "actions", "limitations"],
        "properties": {
            "mode": {"const": "proposal_only"}, "will_write": {"const": False},
            "requires_human_approval": {"const": True},
            "actions": {"type": "array", "items": {
                "type": "object", "required": ["action_id", "finding_ids", "priority", "title", "recommendation",
                                               "owner_proposal", "due_date_proposal", "due_basis", "evidence_requirements",
                                               "acceptance", "status", "will_write"],
                "properties": {
                    "status": {"const": "proposal"}, "will_write": {"const": False},
                    "action_id": {"type": "string", "pattern": "^A-[0-9a-f]{16}$"},
                    "finding_ids": {"type": "array", "items": ID}, "priority": {"enum": list(PRIORITIES)},
                    "title": STRING, "recommendation": STRING, "due_basis": STRING, "acceptance": STRING,
                    "due_date_proposal": {"type": "string", "format": "date"},
                    "evidence_requirements": {"type": "array", "minItems": 1, "items": STRING},
                    "owner_proposal": {
                        "type": "object", "required": ["role", "user_id", "state", "requires_confirmation"],
                        "properties": {"role": ID, "user_id": {"anyOf": [{"type": "integer", "minimum": 1}, {"type": "null"}]},
                                       "state": {"enum": ["existing_id_to_confirm", "role_proposal"]},
                                       "requires_confirmation": {"const": True}},
                    },
                },
            }},
            "limitations": {"type": "array", "items": STRING},
        },
    }, plan)
    if (plan.get("assessment_id") != assessment["assessment_id"]
            or plan.get("assessment_sha256") != assessment["assessment_sha256"]
            or plan.get("mode") != "proposal_only" or plan.get("will_write") is not False):
        raise ValueError("Maßnahmenplan gehört nicht zur unveränderten Bewertung")
    expected = {f["finding_id"] for f in assessment["findings"]}
    referenced = [fid for action in plan["actions"] for fid in action["finding_ids"]]
    if set(referenced) != expected or len(referenced) != len(set(referenced)):
        raise ValueError("Maßnahmenplan muss jeden Befund genau einmal abdecken")
