"""Public distribution policy: synthetic configuration, safe guards, no vendor prose."""
import json
import re
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]


@pytest.mark.parametrize("filename", ["v2_contract.json", "personnel_contract.json"])
def test_legacy_contracts_contain_constraints_not_vendor_examples_or_annotations(filename):
    def check(value, property_map=False):
        if isinstance(value, dict):
            for key, child in value.items():
                if not property_map:
                    assert key not in ("description", "example", "examples", "title", "externalDocs")
                check(child, key in ("properties", "definitions", "$defs"))
        elif isinstance(value, list):
            for child in value:
                check(child)
    contract = json.loads((ROOT / filename).read_text())
    check(contract)
    if filename == "v2_contract.json":
        from v2_core import ALLOWED_FIELDS
        for resource, modes in contract["requests"].items():
            for mode, schema in modes.items():
                assert set(schema["properties"]) == set(ALLOWED_FIELDS[resource][mode])


@pytest.mark.parametrize("allowed", ["0", "-1", "invalid", ""])
def test_public_read_guard_requires_positive_explicit_allowed_tenant(monkeypatch, allowed):
    from audatis_api import AudatisAPI, ConfigurationError
    monkeypatch.setenv("AUDATIS_BASE_URL", "https://tenant.example.test")
    monkeypatch.setenv("AUDATIS_API_TOKEN", "FAKE_READ")
    monkeypatch.setenv("AUDATIS_CLIENT_ID", "12345")
    monkeypatch.setenv("AUDATIS_ALLOWED_CLIENT_ID", allowed)
    with pytest.raises(ConfigurationError):
        AudatisAPI.from_env()


def test_public_read_guard_rejects_cross_tenant_and_accepts_aligned_scope(monkeypatch):
    from audatis_api import AudatisAPI, ConfigurationError
    monkeypatch.setenv("AUDATIS_BASE_URL", "https://tenant.example.test")
    monkeypatch.setenv("AUDATIS_API_TOKEN", "FAKE_READ")
    monkeypatch.setenv("AUDATIS_CLIENT_ID", "12345")
    monkeypatch.setenv("AUDATIS_ALLOWED_CLIENT_ID", "54321")
    with pytest.raises(ConfigurationError):
        AudatisAPI.from_env()
    monkeypatch.setenv("AUDATIS_ALLOWED_CLIENT_ID", "12345")
    assert AudatisAPI.from_env().client_id == 12345


def test_zero_tenant_cannot_load_specialized_write_credentials(monkeypatch):
    import task_direct
    import task_management
    import asset_management
    monkeypatch.setenv("AUDATIS_CLIENT_ID", "0")
    for module in (task_direct, task_management, asset_management):
        monkeypatch.setattr(module, "EXPECTED_CLIENT_ID", 0)
        monkeypatch.setattr(module, "_write_token", lambda: pytest.fail("Zero guard read write credentials"))
    with pytest.raises(RuntimeError):
        task_direct.create_task("Synthetic task")
    with pytest.raises(RuntimeError):
        task_management._settings()
    with pytest.raises(RuntimeError):
        asset_management._settings()


def test_v2_constructor_rejects_nonpositive_tenant(monkeypatch):
    import v2_core
    monkeypatch.setattr(v2_core, "EXPECTED_CLIENT_ID", 0)
    with pytest.raises(ValueError):
        v2_core.V2API("https://tenant.example.test", "FAKE_READ", client_id=0)


def test_public_readme_links_resolve():
    text = (ROOT / "README.md").read_text()
    for link in re.findall(r"\[[^\]]+\]\(([^)]+)\)", text):
        if not link.startswith(("https://", "http://")):
            assert (ROOT / link.split("#", 1)[0]).is_file(), link
