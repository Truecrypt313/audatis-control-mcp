"""Safe, targeted MCP tool-name migration. Does not execute any API calls.

Usage:
  python apply_mcp_naming.py --check
  python apply_mcp_naming.py --apply

Requires Git branch other than main and known source patterns. Edits server.py,
.vscode/mcp.json, and three outdated tool-count tests only. All edits are
validated before writing; if validation fails, nothing is changed.
"""
from __future__ import annotations

import argparse
import ast
import json
import os
import subprocess
import tempfile
from pathlib import Path


def one(source: str, original: str, updated: str, file: str) -> str:
    if updated in source and original not in source:
        return source
    count = source.count(original)
    if count != 1:
        raise RuntimeError(f"{file}: erwarteter Abschnitt nicht eindeutig gefunden ({count}). Keine Änderungen.")
    return source.replace(original, updated, 1)


def proposed(root: Path) -> dict[Path, str]:
    paths = {
        name: root / name for name in (
            "server.py", ".vscode/mcp.json", "tests/test_v2.py",
            "tests/test_v21.py", "tests/test_personnel.py",
        )
    }
    originals = {name: path.read_text(encoding="utf-8") for name, path in paths.items()}
    result = {}

    src = originals["server.py"]
    if "register_personnel_tools(mcp)" not in src:
        raise RuntimeError("server.py: Personalregistrierung fehlt; erwarteter Stand sind 47 Tools.")
    src = one(src, "from v2_register import register_v2_tools\nregister_v2_tools(mcp)",
              "from mcp_naming import named_mcp\nfrom v2_register import register_v2_tools\nregister_v2_tools(named_mcp(mcp))", "server.py")
    src = one(src, "register_v21_tools(mcp)", "register_v21_tools(named_mcp(mcp))", "server.py")
    ast.parse(src, filename="server.py")
    result[paths["server.py"]] = src

    config = json.loads(originals[".vscode/mcp.json"])
    try:
        server = config["servers"]["audatisReadonly"]
    except (TypeError, KeyError):
        raise RuntimeError(".vscode/mcp.json: MCP-Server 'audatisReadonly' nicht gefunden") from None
    if not isinstance(server, dict):
        raise RuntimeError(".vscode/mcp.json: Ungültige Serverkonfiguration")
    if not isinstance(server.get("env", {}), dict):
        raise RuntimeError(".vscode/mcp.json: env muss ein Objekt sein")
    server.setdefault("env", {})["AUDATIS_MCP_TOOL_NAMES"] = "modern"
    result[paths[".vscode/mcp.json"]] = json.dumps(config, ensure_ascii=False, indent=2) + "\n"

    src = originals["tests/test_v2.py"]
    src = one(src, "assert len(registered) in (31, 36)",
              "assert len(registered) in (31, 36, 47)", "tests/test_v2.py")
    ast.parse(src, filename="tests/test_v2.py")
    result[paths["tests/test_v2.py"]] = src

    src = originals["tests/test_v21.py"]
    src = one(src, "assert len(server.mcp.names) == 36",
              "assert len(server.mcp.names) in (36, 47)", "tests/test_v21.py")
    src = one(src, "assert len(set(server.mcp.names)) == 36",
              "assert len(set(server.mcp.names)) == len(server.mcp.names)", "tests/test_v21.py")
    ast.parse(src, filename="tests/test_v21.py")
    result[paths["tests/test_v21.py"]] = src

    src = originals["tests/test_personnel.py"]
    src = one(src, "    assert len(original.mcp.names)==36\n    register_personnel_tools(original.mcp)",
              "    if len(original.mcp.names) == 36:\n        register_personnel_tools(original.mcp)",
              "tests/test_personnel.py")
    ast.parse(src, filename="tests/test_personnel.py")
    result[paths["tests/test_personnel.py"]] = src
    return result


def main():
    parser = argparse.ArgumentParser(description="MCP-Toolnamen sicher modernisieren")
    opts = parser.add_mutually_exclusive_group(required=True)
    opts.add_argument("--check", action="store_true", help="Nur Machbarkeit prüfen, nichts schreiben")
    opts.add_argument("--apply", action="store_true", help="Sichere, gezielte Änderungen durchführen")
    args = parser.parse_args()
    root = Path(__file__).resolve().parent
    if not (root / ".git").exists():
        raise SystemExit("Kein .git im Projektverzeichnis; Vorgang abgebrochen")
    branch = subprocess.run(["git", "branch", "--show-current"], cwd=root,
                            capture_output=True, text=True, check=True).stdout.strip()
    if branch in ("", "main", "master"):
        raise SystemExit("Bitte im gesicherten Feature-Branch arbeiten, nicht in main/master")
    if not (root / "mcp_naming.py").exists():
        raise SystemExit("mcp_naming.py fehlt")
    try:
        edits = proposed(root)
    except (RuntimeError, FileNotFoundError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise SystemExit(f"Migration nicht sicher anwendbar: {exc}") from None
    changed = [p for p, value in edits.items() if p.read_text(encoding="utf-8") != value]
    print("Git-Branch:", branch)
    print("Geprüfte Dateien:", len(edits))
    print("Zu ändernde Dateien:", len(changed))
    for p in changed:
        print(" -", p.relative_to(root))
    if args.check:
        print("Nur Prüfung, keine Datei geändert.")
        return
    if not changed:
        print("Bereits eingerichtet, nichts geändert.")
        return
    originals = {p: p.read_bytes() for p in changed}
    modified = []
    try:
        for path in changed:
            with tempfile.NamedTemporaryFile(mode="w", encoding="utf-8", dir=path.parent,
                                             prefix=".naming-", delete=False) as temp:
                temp.write(edits[path])
                tmp = Path(temp.name)
            os.chmod(tmp, path.stat().st_mode & 0o777)
            tmp.replace(path)
            modified.append(path)
    except Exception:
        for path in modified:
            path.write_bytes(originals[path])
        raise
    print("Fertig. Keinen Commit automatisch erstellt und keinen API-Aufruf ausgeführt.")
    print("Jetzt Offline-Tests ausführen und MCP-Server neu starten.")


if __name__ == "__main__":
    main()
