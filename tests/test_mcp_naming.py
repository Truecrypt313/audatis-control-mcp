"""Pure offline tests: no stdio transport, environment tokens, or HTTP calls."""
from __future__ import annotations

from inspect import signature

import pytest

from mcp_naming import TOOL_NAME_MAP, NAMING_ENV, named_mcp, naming_mode
from personnel_register import PERSONNEL_TOOLS, register_personnel_tools
from v2_register import V2_TOOLS, register_v2_tools
from v21_register import V21_TOOLS, register_v21_tools


class FakeMCP:
    def __init__(self):
        self.registry = {}

    def tool(self):
        def register(fn):
            assert fn.__name__ not in self.registry, 'Duplicate tool: ' + fn.__name__
            self.registry[fn.__name__] = fn
            return fn
        return register


def test_mapping_exactly_matches_all_versioned_tool_functions():
    sources = V2_TOOLS + V21_TOOLS
    assert len(sources) == len(TOOL_NAME_MAP) == 20
    assert set(TOOL_NAME_MAP) == {x.__name__ for x in sources}
    assert len(set(TOOL_NAME_MAP.values())) == 20
    assert all(not x.startswith(('v2_', 'v21_', 'v22_')) for x in TOOL_NAME_MAP.values())
    existing = {x.__name__ for x in PERSONNEL_TOOLS}
    assert existing.isdisjoint(TOOL_NAME_MAP.values())


def test_default_mode_unchanged(monkeypatch):
    monkeypatch.delenv(NAMING_ENV, raising=False)
    assert naming_mode() == 'legacy'
    f = FakeMCP()
    register_v2_tools(named_mcp(f))
    register_v21_tools(named_mcp(f))
    assert set(f.registry) == set(TOOL_NAME_MAP)


def test_modern_mode_same_count_and_signatures(monkeypatch):
    monkeypatch.setenv(NAMING_ENV, 'modern')
    f = FakeMCP()
    register_v2_tools(named_mcp(f))
    register_v21_tools(named_mcp(f))
    register_personnel_tools(f)
    assert len(f.registry) == 31
    assert set(TOOL_NAME_MAP.values()).issubset(f.registry)
    assert all(not n.startswith(('v2_', 'v21_')) for n in f.registry)
    for original in V2_TOOLS + V21_TOOLS:
        alias = f.registry[TOOL_NAME_MAP[original.__name__]]
        assert signature(alias) == signature(original)
        assert alias.__doc__ == original.__doc__


def test_invalid_mode_fails_closed(monkeypatch):
    monkeypatch.setenv(NAMING_ENV, 'modren')
    with pytest.raises(ValueError, match=NAMING_ENV):
        named_mcp(FakeMCP())


def test_modern_error_names_and_dry_run_no_network(monkeypatch):
    import v2_bulk
    monkeypatch.setenv(NAMING_ENV, 'modern')
    monkeypatch.setattr(v2_bulk.V2API, 'from_env', staticmethod(
        lambda: pytest.fail('Dry-run must not touch API')))
    f = FakeMCP()
    register_v2_tools(named_mcp(f))
    result = f.registry['bulk_create_records'](
        resource='tasks',
        items_json='[{"subject":"MCP Test","unknown_field":"X"}]',
        execute=False,
    )
    assert result['ok'] is False
    assert result['tool'] == 'bulk_create_records'
    assert result['error_type'] == 'validation_error'
    assert 'unknown_field' in result['error']
    success = f.registry['bulk_create_records'](
        resource='tasks', items_json='[{"subject":"MCP Test"}]', execute=False)
    assert success['execute'] is False


def test_unversioned_personnel_names_remain_unchanged(monkeypatch):
    monkeypatch.setenv(NAMING_ENV, 'modern')
    f = FakeMCP()
    register_personnel_tools(f)
    assert len(f.registry) == 11
    assert 'create_personnel' in f.registry
    assert 'assign_personnel_organisations' in f.registry
