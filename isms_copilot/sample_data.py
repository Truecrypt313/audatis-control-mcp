"""Synthetic runtime sample for MCP/CLI tests; no environment or customer data."""
from __future__ import annotations

from copy import deepcopy
from uuid import UUID

from .model import RESOURCES, empty_bundle, source


def object_id(number: int) -> str:
    return str(UUID(int=number))


def synthetic_monitoring(number: int) -> dict:
    return {
        "definition": {"measurement_subject": "Synthetischer Kontrollnachweis",
                       "measurement_method": "Fiktives Testszenario, kein real ausgeführter Test",
                       "measurement_type": "text", "direction": 1,
                       "measurement_frequency": "monthly", "review_frequency": "quarterly",
                       "is_escalation_active": False, "tolerance_days": 0,
                       "is_auto_task_measurement": False, "is_auto_task_review": False},
        "measurements": [{"id": object_id(number), "measured_at": "2026-11-13",
                          "traffic_light": "green", "text_value": "Synthetischer Testnachweis im Demo-Szenario",
                          "data_source": "synthetic:DEMO-NACHWEIS"}],
        "reviews": [{"id": object_id(number + 1), "reviewed_at": "2026-11-13",
                     "effectiveness_rating": "effective",
                     "effectiveness_justification": "Fiktive Reviewentscheidung; keine reale Wirksamkeitsprüfung",
                     "summary": "Nur synthetische Portfolio-Demonstration"}],
    }


def portfolio_case(phase: str = "initial", department: str = "all") -> dict:
    if phase not in ("initial", "follow_up") or department not in ("all", "it", "production"):
        raise ValueError("phase: initial/follow_up; department: all/it/production")
    a1, a2, a3, i1, i2, p1, p2, m1, m2, r1, r2, t1, t2 = [object_id(n) for n in range(101, 114)]
    missing = object_id(999)
    rows = {
        "assets": [
            {"id": a1, "title": "DEMO-ERP-01", "description": "Fiktives Auftragsplanungssystem.",
             "asset_owner_user_id": 90001, "protection_needs": {"confidentiality": 2, "integrity": 2, "availability": 2},
             "information_values": [{"information_value_id": i1}], "measures": [{"measure_id": m1}],
             "linked_assets": [], "parent_id": None, "is_group": False},
            {"id": a2, "title": "DEMO-BACKUP-01", "description": None, "asset_owner_user_id": None,
             "protection_needs": {"confidentiality": None, "integrity": None, "availability": None},
             "information_values": [], "measures": [], "linked_assets": [], "parent_id": None, "is_group": False},
            {"id": a3, "title": "DEMO-CLIENT-01", "description": "Fiktiver Beratungsarbeitsplatz.",
             "asset_owner_user_id": 90002, "protection_needs": {"confidentiality": 1, "integrity": 1, "availability": 1},
             "information_values": [{"information_value_id": missing}], "measures": [{"measure_id": m1}],
             "linked_assets": [], "parent_id": None, "is_group": False},
        ],
        "information-values": [
            {"id": i1, "title": "DEMO-Auftragsdaten", "description": "Synthetische Auftrags- und Fertigungsdaten ohne echte Inhalte.",
             "asset_owner_user_id": 90003, "protection_needs": {"confidentiality": {"level": "high"}, "integrity": {"level": "high"}, "availability": {"level": "high"}},
             "linked_assets": [{"asset_id": a1}], "next_review_at": "2026-12-01"},
            {"id": i2, "title": "DEMO-Backupkatalog", "description": "Fiktives Verzeichnis gesicherter Datenbestände.",
             "asset_owner_user_id": None, "protection_needs": {"confidentiality": {"level": "normal"}, "integrity": {"level": "normal"}, "availability": {"level": "inherited"}},
             "linked_assets": [], "next_review_at": None},
        ],
        "business-processes": [
            {"id": p1, "title": "DEMO-Auftragsabwicklung", "description": "Fiktiver Auftrag bis Fertigungsfreigabe.",
             "process_owner_id": 90003, "process": {"goal": "Aufträge nachvollziehbar abwickeln", "input": "Synthetischer Auftrag", "output": "Freigabe", "steps": "Prüfen, planen, freigeben"},
             "asset_ids": [a1], "information_value_ids": [i1], "measure_ids": [m1], "risk_ids": [r2],
             "parent_id": None, "next_review_at": "2026-12-01"},
            {"id": p2, "title": "DEMO-Datensicherung", "description": None, "process_owner_id": None,
             "process": {"goal": None, "input": None, "output": None, "steps": None},
             "asset_ids": [], "information_value_ids": [], "measure_ids": [], "risk_ids": [r1],
             "parent_id": None, "next_review_at": "2026-11-01"},
        ],
        "measures": [
            {"id": m1, "title": "DEMO-Rollenreview", "description": "Fiktiver regelmäßiger Rollenabgleich.",
             "responsible_user_id": 90002, "implementation_status": "implemented",
             "monitoring": synthetic_monitoring(501), "asset_ids": [a1, a3],
             "business_process_ids": [p1], "risk_ids": [r2], "next_review_at": "2026-12-01"},
            {"id": m2, "title": "DEMO-Restoretest", "description": "Geplanter Wiederherstellungsnachweis im fiktiven Szenario.",
             "responsible_user_id": None, "implementation_status": "planned", "monitoring": None,
             "asset_ids": [], "business_process_ids": [], "risk_ids": [r1], "next_review_at": None},
        ],
        "risks": [
            {"id": r1, "designation": "DEMO-R-001 Backupbewertung", "description": "Fiktiver Bewertungsbedarf; kein bestätigter technischer Mangel.",
             "owner_user_id": None, "responsible_user_id": None, "status_code": "in_treatment",
             "gross_risk": None, "net_risk": None, "target_risk": None},
            {"id": r2, "designation": "DEMO-R-002 Rollenbewertung", "description": "Synthetische bereits dokumentierte Bewertung.",
             "owner_user_id": 90002, "responsible_user_id": 90002, "status_code": "approved",
             "gross_risk": 2, "net_risk": 1, "target_risk": 1},
        ],
        "tasks": [
            {"id": t1, "subject": "DEMO-Restoretest abstimmen", "description": "Fiktiven Restoretest planen und Ergebnisse dokumentieren.",
             "assigned_to_user_id": None, "status": "open", "due_date": "2026-11-07"},
            {"id": t2, "subject": "DEMO-Rollenreview abstimmen", "description": "Fiktiven Fachreview bestätigen.",
             "assigned_to_user_id": 90002, "status": "open", "due_date": "2026-12-01"},
        ],
    }
    if phase == "follow_up":
        rows["assets"][1].update(description="Fiktive Backupablage. Synthetische C/I/A-Begründung: geschäftliche Sicherungsdaten, "
                                  "unveränderte Wiederherstellung und Wiederanlauf sind im Demo-Scope jeweils als hoch bewertet.",
                                  asset_owner_user_id=90001,
                                  protection_needs={"confidentiality": 2, "integrity": 2, "availability": 2},
                                  information_values=[{"information_value_id": i2}], measures=[{"measure_id": m2}])
        rows["information-values"][1].update(asset_owner_user_id=90001,
            protection_needs={"confidentiality": {"level": "normal", "reason": "Synthetisch: Katalog ohne produktive Dateninhalte"},
                              "integrity": {"level": "high", "reason": "Synthetisch: korrekte Zuordnung der Sicherungen erforderlich"},
                              "availability": {"level": "high", "reason": "Synthetisch: Katalog wird beim Wiederanlauf benötigt"}},
            linked_assets=[{"asset_id": a2}], next_review_at="2026-12-14")
        rows["business-processes"][1].update(description="Fiktiver Sicherungs- und Restoreprozess.", process_owner_id=90001,
            process={"goal": "Wiederherstellbarkeit nachweisen", "input": "Sicherungsumfang", "output": "Testprotokoll", "steps": "Sichern, wiederherstellen, prüfen"},
            asset_ids=[a2], information_value_ids=[i2], measure_ids=[m2], next_review_at="2026-12-14")
        rows["measures"][1].update(responsible_user_id=90001, implementation_status="implemented",
            monitoring=synthetic_monitoring(503), asset_ids=[a2], business_process_ids=[p2], next_review_at="2026-12-14")
        rows["risks"][0].update(owner_user_id=90001, responsible_user_id=90001, gross_risk=3, net_risk=2, target_risk=2)
        rows["tasks"][0].update(assigned_to_user_id=90001, status="completed")
    scopes = {
        "it": {"name": "Fiktiver Fachbereich IT-Betrieb", "object_ids": {
            "assets": [a2, a3], "information-values": [i2], "business-processes": [p2],
            "measures": [m2], "risks": [r1], "tasks": [t1]}},
        "production": {"name": "Fiktiver Fachbereich Fertigung", "object_ids": {
            "assets": [a1], "information-values": [i1], "business-processes": [p1],
            "measures": [m1], "risks": [r2], "tasks": [t2]}},
    }
    bundle = empty_bundle("Fiktiva Werkzeugbau – rein fiktives Portfolio-Szenario",
                          "2026-11-14", "2026-11-14T10:00:00+01:00", "synthetic:fiktiva-demo",
                          synthetic=True, scope=deepcopy(scopes.get(department)))
    ref = source("lookup_values", {"name": "asset_protection_levels"}, bundle["context"]["client_reference"],
                 {"levels": [{"level": 1, "name": "Normal"}, {"level": 2, "name": "Hoch"}, {"level": 3, "name": "Sehr hoch"}]})
    bundle["sources"].append(ref)
    bundle["references"]["asset_protection_levels"] = ref["source_id"]
    for resource in RESOURCES:
        page = source("list_records", {"resource": resource, "page": 1, "per_page": 100},
                      bundle["context"]["client_reference"],
                      {"ids": [obj["id"] for obj in rows[resource]], "meta": {"page": 1, "total": len(rows[resource]), "total_pages": 1}})
        bundle["sources"].append(page)
        info = bundle["resources"][resource]
        info.update(state="partial" if resource == "information-values" and phase == "initial" else "complete",
                    reason="Synthetischer, absichtlich unvollständiger Auszug" if resource == "information-values" and phase == "initial" else "Synthetischer vollständiger Sichtbestand")
        info["source_ids"].append(page["source_id"])
        for obj in rows[resource]:
            entry = source("get_record", {"resource": resource, "record_id": obj["id"]},
                           bundle["context"]["client_reference"], obj)
            bundle["sources"].append(entry)
            info["records"].append(entry["source_id"])
            info["source_ids"].append(entry["source_id"])
    return bundle
