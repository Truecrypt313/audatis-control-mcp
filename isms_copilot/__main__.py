"""Offline asset demo/assessment; exports stay in the configured private output root."""
from __future__ import annotations

import argparse
import json
import os
import tempfile
from pathlib import Path

from .assessment import assess
from .model import parse_json, seal
from .planner import plan_remediation
from .asset_demo import asset_demo_bundle
from .report import render_report
from .tools import build_consulting_brief


def json_file(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, indent=2, allow_nan=False) + "\n"


def artifacts(bundle: dict) -> dict[str, str]:
    result = assess(bundle)
    plan = plan_remediation(result)
    report = render_report(result, plan)
    details = seal({"bundle": bundle, "assessment": result, "plan": plan,
                    "report_sha256": report["report_sha256"],
                    "selection": report.get("technical_details", {}).get("finding_groups", []),
                    "consulting_brief": build_consulting_brief(json_file(result))}, "details_sha256")
    return {"details.json": json_file(details), "report.md": report["markdown"], "report.html": report["html"]}


def demo_artifacts() -> dict[str, str]:
    return artifacts(asset_demo_bundle())


def output_path(requested):
    root = Path(os.environ.get("AUDATIS_COPILOT_OUTPUT_DIR") or Path(__file__).resolve().parents[1] / "copilot-output").absolute()
    output = Path(requested) if requested else root
    if requested and not output.is_absolute():
        output = root / output
    if any(p.is_symlink() for p in (output, *output.parents, root, *root.parents)):
        raise ValueError("Keine Ausgabe über Symlinks")
    if not output.resolve().is_relative_to(root.resolve()):
        raise ValueError("Ausgabe muss im konfigurierten lokalen Ausgabeordner bleiben")
    if root.exists() and root.stat().st_mode & 0o077:
        raise ValueError("Ausgabeordner muss private Berechtigungen haben (0700)")
    return root, output


def write_artifacts(output: Path, files: dict[str, str], *, check=False, overwrite=False):
    # Preflight ALL outputs before writing, to avoid overwriting user work.
    for name, content in files.items():
        if Path(name).is_absolute() or ".." in Path(name).parts:
            raise ValueError("Artefaktname darf den Ausgabebereich nicht verlassen")
        target = output / name
        if output.is_symlink() or any(parent.is_symlink() for parent in (target, *target.parents)):
            raise ValueError("Keine Ausgabe über Symlinks")
        if check and (not target.is_file() or target.read_bytes() != content.encode("utf-8")):
            raise ValueError("Demo-Artefakte fehlen oder sind nicht reproduzierbar")
        if target.exists() and target.read_bytes() != content.encode("utf-8") and not (overwrite or check):
            raise ValueError("Ausgabedatei existiert mit anderem Inhalt; --overwrite nur nach Prüfung verwenden")
    if check:
        return
    output.mkdir(parents=True, exist_ok=True, mode=0o700)
    for name, content in files.items():
        target = output / name
        target.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        temporary = None
        try:
            with tempfile.NamedTemporaryFile(mode="w", encoding="utf-8", dir=target.parent,
                                             prefix=".copilot-", delete=False) as stream:
                temporary = Path(stream.name)
                os.fchmod(stream.fileno(), 0o600)
                stream.write(content)
            os.replace(temporary, target)  # Replace a hardlink, never truncate its outside target.
        finally:
            if temporary is not None:
                temporary.unlink(missing_ok=True)


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    demo = sub.add_parser("demo", help="Drei synthetische Assets; keine API-Aufrufe")
    local = sub.add_parser("assess", help="Lokal bereitgestelltes Evidence-Bundle bewerten")
    local.add_argument("bundle", type=Path)
    local.add_argument("--scope", type=Path, help="Lokale Fachbereichsauswahl als Scope-JSON")
    for command in (demo, local):
        command.add_argument("--output", type=Path, help="Unterordner innerhalb AUDATIS_COPILOT_OUTPUT_DIR")
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
        root, output = output_path(args.output)
        if not args.check:
            root.mkdir(parents=True, exist_ok=True, mode=0o700)
        write_artifacts(output, files, check=args.check, overwrite=args.overwrite)
    except (ValueError, OSError):
        parser.error("Eingabe/Ausgabe nicht auswertbar; Schema, Pfade und vorhandene Dateien prüfen")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
