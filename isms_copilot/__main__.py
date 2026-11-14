"""Offline CLI: python -m isms_copilot demo|assess --output PATH."""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path

from .assessment import assess
from .model import parse_json
from .planner import plan_remediation
from .sample_data import portfolio_case
from .report import render_report
from .tools import build_consulting_brief


def json_file(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, indent=2, allow_nan=False) + "\n"


def artifacts(bundle: dict) -> dict[str, str]:
    result = assess(bundle)
    plan = plan_remediation(result)
    report = render_report(result, plan)
    return {"evidence.json": json_file(bundle), "assessment.json": json_file(result),
            "remediation.json": json_file(plan), "report.md": report["markdown"],
            "report.html": report["html"],
            "consulting_brief.json": json_file(build_consulting_brief(json_file(result)))}


def demo_artifacts(*, include_presentation=False) -> dict[str, str]:
    output = {}
    results = {}
    for phase in ("initial", "follow_up"):
        bundle = portfolio_case(phase)
        results[phase] = assess(bundle)
        output.update({phase + "/" + name: value for name, value in artifacts(bundle).items()})
    for department in ("it", "production"):
        output.update({"departments/" + department + "/" + name: value
                       for name, value in artifacts(portfolio_case("initial", department)).items()})
    before, after = results["initial"]["summary"], results["follow_up"]["summary"]
    comparison = (
        "# Fiktiver Follow-up-Vergleich\n\n"
        "**Ausschließlich synthetische Szenarien, keine realen Änderungen oder Kontrolltests.**\n\n"
        "| Kennzahl | Initial | Fiktiver Follow-up |\n|---|---:|---:|\n"
        + f"| Befunde | {before['findings']} | {after['findings']} |\n"
        + "".join(f"| {s} | {before['by_status'][s]} | {after['by_status'][s]} |\n" for s in before["by_status"])
        + "\nVerbesserte Dokumentation ist kein Nachweis höherer tatsächlicher Sicherheit. "
        "Eine nicht auflösbare Referenz bleibt bewusst nicht überprüfbar. Keine ISO-/NIS-2-Konformitätsaussage.\n"
    )
    output["comparison.md"] = comparison
    if include_presentation:
        # Private presentation extension is not part of the public distribution.
        from .presentation import presentation
        output.update(presentation(results["initial"], results["follow_up"], plan_remediation(results["initial"])))
    return output


def write_artifacts(output: Path, files: dict[str, str], *, check=False, overwrite=False):
    # Preflight ALL outputs before writing, to avoid overwriting user work.
    for name, content in files.items():
        if Path(name).is_absolute() or ".." in Path(name).parts:
            raise ValueError("Artefaktname darf den Ausgabebereich nicht verlassen")
        target = output / name
        if output.is_symlink() or any(parent.is_symlink() for parent in (target, *target.parents)):
            raise ValueError("Keine Ausgabe über Symlinks")
        if check and (not target.is_file() or target.read_text(encoding="utf-8") != content):
            raise ValueError("Demo-Artefakte fehlen oder sind nicht reproduzierbar")
        if target.exists() and target.read_text(encoding="utf-8") != content and not (overwrite or check):
            raise ValueError("Ausgabedatei existiert mit anderem Inhalt; --overwrite nur nach Prüfung verwenden")
    if check:
        return
    output.mkdir(parents=True, exist_ok=True, mode=0o700)
    for name, content in files.items():
        target = output / name
        target.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        flags = os.O_WRONLY | os.O_CREAT | os.O_TRUNC | getattr(os, "O_NOFOLLOW", 0)
        descriptor = os.open(target, flags, 0o600)
        with os.fdopen(descriptor, "w", encoding="utf-8") as stream:
            os.fchmod(stream.fileno(), 0o600)
            stream.write(content)


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    demo = sub.add_parser("demo", help="Vollständig synthetischer Portfolio-Prozess")
    local = sub.add_parser("assess", help="Lokal bereitgestelltes Evidence-Bundle bewerten")
    local.add_argument("bundle", type=Path)
    local.add_argument("--scope", type=Path, help="Lokale Fachbereichsauswahl als Scope-JSON")
    for command in (demo, local):
        command.add_argument("--output", type=Path, required=True)
        command.add_argument("--check", action="store_true")
        command.add_argument("--overwrite", action="store_true")
    args = parser.parse_args(argv)
    try:
        if args.command == "demo":
            files = demo_artifacts()
        else:
            if args.bundle.stat().st_size > 5 * 1024 * 1024:
                raise ValueError("Evidence-Bundle zu groß")
            bundle = parse_json(args.bundle.read_text(encoding="utf-8"))
            if args.scope:
                if args.scope.stat().st_size > 100000:
                    raise ValueError("Scope-Datei zu groß")
                bundle["context"]["scope"] = parse_json(args.scope.read_text(encoding="utf-8"), maximum=100000)
            files = artifacts(bundle)
        write_artifacts(args.output, files, check=args.check, overwrite=args.overwrite)
    except (ValueError, OSError):
        parser.error("Eingabe/Ausgabe nicht auswertbar; Schema, Pfade und vorhandene Dateien prüfen")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
