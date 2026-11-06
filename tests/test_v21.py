"""Offline regression suite for 2.1: no network and no real tenant data."""
from __future__ import annotations

import inspect
import json
from copy import deepcopy

import httpx
import pytest

from v2_core import V2API, BASE
import v21_relationships as rel
import v21_hierarchy as hier
from v21_register import V21_TOOLS, register_v21_tools

A = '8bf9b3bd-5065-4707-9b6c-4568e3460e2e'
B = 'e4fcf3d0-e04a-45fc-838d-55b9cb0582b9'
C = 'e4fcf3d0-e04a-45fc-838d-55b9cb0582b8'
I = '7bce283d-4f8d-4c63-bac9-c33552b83d95'
P = 'e111363d-19c1-4f8a-b816-72c4eb95e8a0'
M = '374ea296-b201-49c8-90ba-e77037be8e90'
R = '01a1ab5d-4606-73a2-90f7-5b7fe6185776'


def sample():
    return {
        'assets': [
            {'id': A, 'title': 'Firewall', 'is_group': True, 'asset_owner_user_id': 1,
             'parent_id': None, 'linked_assets': [
                 {'asset_id': B, 'relationship_type': 'depends_on', 'direction': 'outgoing'}],
             'information_values': [{'information_value_id': I}],
             'measures': [{'measure_id': M}], 'risks': [{'risk_id': R}],
             'protection_needs': {'confidentiality': 2, 'integrity': 3, 'availability': 2}},
            {'id': B, 'title': 'Server', 'is_group': False, 'asset_owner_user_id': 1,
             'parent_id': None, 'linked_assets': [
                 {'asset_id': A, 'relationship_type': 'depends_on', 'direction': 'incoming'}],
             'information_values': [], 'measures': [], 'risks': []},
            {'id': C, 'title': 'Workstation', 'is_group': False, 'asset_owner_user_id': None,
             'parent_id': None, 'linked_assets': [], 'information_values': [], 'measures': [], 'risks': []}
        ],
        'information-values': [{'id': I, 'title': 'Credentials', 'asset_owner_user_id': 1,
                                'linked_assets': [{'asset_id': A}],
                                'protection_needs': {'confidentiality': {'level': 'high'},
                                                     'integrity': {'level': 'normal'},
                                                     'availability': {'level': 'inherited'}}}],
        'business-processes': [{'id': P, 'title': 'Restore', 'process_owner_id': None,
                                'parent_id': None, 'asset_ids': [A], 'information_value_ids': [I],
                                'measure_ids': [M], 'risk_ids': [], 'sub_process_ids': []}],
        'measures': [{'id': M, 'title': 'Backups', 'responsible_user_id': 2,
                      'asset_ids': [A], 'business_process_ids': [P], 'risk_ids': [R]}],
        'risks': [{'id': R, 'designation': 'Missing backup'}],
    }


def build_api(db=None, *, fail_put_at=None, fail_after_update=False, pagination_truncated=False):
    db = deepcopy(db if db is not None else sample())
    calls = []
    def handler(req):
        calls.append(req)
        path = req.url.path
        assert path.startswith(BASE + '/')
        tail = path[len(BASE) + 1:]
        parts = tail.split('/')
        resource = parts[0]
        assert resource in db, resource
        if req.method == 'GET' and len(parts) == 1:
            # The transport returns at most 100 items like a real paginated API.
            items = db[resource]
            if pagination_truncated and resource == 'assets':
                return httpx.Response(200, json={'data': items[:100], 'meta': {'total_pages': 2}})
            return httpx.Response(200, json={'data': deepcopy(items), 'meta': {'total_pages': 1}})
        assert len(parts) == 2
        rid = parts[1]
        target = next((x for x in db[resource] if x['id'] == rid), None)
        if target is None:
            return httpx.Response(404, json={'message': 'missing'})
        if req.method == 'GET':
            return httpx.Response(200, json={'data': deepcopy(target)})
        if req.method == 'PUT':
            if fail_put_at == rid:
                return httpx.Response(422, json={'message': 'validation'})
            body = json.loads(req.content)
            assert 'title' in body
            target.update(body)
            if fail_after_update:
                return httpx.Response(500, json={'message': 'write may have completed'})
            return httpx.Response(200, json={'data': deepcopy(target)})
        pytest.fail('Only GET/PUT allowed')
    api = V2API('https://tenant.example.test', 'FAKE_READ', write_token='FAKE_WRITE',
                transport=httpx.MockTransport(handler))
    return api, db, calls


def patched_api(monkeypatch, api):
    monkeypatch.setattr(rel.V2API, 'from_env', staticmethod(lambda: api))
    monkeypatch.setattr(hier.V2API, 'from_env', staticmethod(lambda: api))


def test_capabilities_match_openapi_restrictions():
    cap = rel.v21_relationship_capabilities()
    assert cap['client_id'] == 12345
    assert 'arbitrary asset-to-asset POST links' in cap['not_supported']
    assert 'assets.parent_id' in cap['supported_link_writes']


def test_graph_merges_both_sides_and_includes_processes_and_risks():
    api, db, calls = build_api()
    out = rel.build_relationship_graph(api)
    assert out['complete'] is True
    assert out['counts']['assets'] == 3
    assert out['counts']['information-values'] == 1
    assert len(out['nodes']) == 7
    got = {(e['source'], e['target'], e['relation']): e for e in out['edges']}
    x = got[(f'assets:{A}', f'information-values:{I}', 'asset_information')]
    assert len(x['observed_in']) == 2
    assert (f'business-processes:{P}', f'assets:{A}', 'process_asset') in got
    assert (f'business-processes:{P}', f'measures:{M}', 'process_measure') in got
    assert (f'risks:{R}', f'measures:{M}', 'risk_measure') in got
    assert (f'assets:{A}', f'assets:{B}', 'asset_relation:depends_on') in got
    assert {q.method for q in calls} == {'GET'}


def test_graph_unresolved_reference_does_not_claim_target_deleted():
    db = sample()
    db['assets'][0]['information_values'] = [{'information_value_id': C}]
    api, _, _ = build_api(db)
    out = rel.build_relationship_graph(api)
    assert any(x['reference'] == f'information-values:{C}' and x['inventory_complete'] for x in out['unresolved'])
    assert 'archiviert' in out['unresolved'][0]['note']


def test_graph_respects_edge_limit_and_reports_incompleteness():
    api, _, _ = build_api()
    out = rel.build_relationship_graph(api, max_edges=1)
    assert out['complete'] is False and out['edges_truncated'] is True


def test_related_records_follows_two_hops_without_causal_claim(monkeypatch):
    api, _, calls = build_api()
    patched_api(monkeypatch, api)
    out = rel.v21_related_records('assets', B, max_depth=2)
    assert any(x['node']['key'] == f'information-values:{I}' and x['distance'] == 2 for x in out['related'])
    assert 'keine Aussage' in out['note']
    assert all(q.method == 'GET' for q in calls)


def test_related_records_rejects_absent_node_and_invalid_depth(monkeypatch):
    api, _, _ = build_api()
    patched_api(monkeypatch, api)
    with pytest.raises(ValueError, match='max_depth'):
        rel.v21_related_records('assets', B, max_depth=4)
    with pytest.raises(ValueError, match='nicht vorhanden'):
        rel.v21_related_records('assets', '00000000-0000-0000-0000-000000000000')


def test_audit_is_read_only_and_identifies_owners(monkeypatch):
    api, _, calls = build_api()
    patched_api(monkeypatch, api)
    out = rel.v21_relationship_audit()
    assert out['issue_count'] >= 2
    assert ('business-processes', P, 'missing_owner') in {
        (x['resource'], x['id'], x['issue']) for x in out['issues']}
    assert ('assets', C, 'missing_owner') in {
        (x['resource'], x['id'], x['issue']) for x in out['issues']}
    assert {q.method for q in calls} == {'GET'}


def test_dry_run_checks_live_graph_but_does_not_write(monkeypatch):
    api, _, calls = build_api()
    patched_api(monkeypatch, api)
    out = hier.v21_bulk_set_parent('assets', json.dumps([{'record_id': B, 'parent_id': A}]))
    assert out['execute'] is False and out['preview'][0]['action'] == 'set_parent'
    assert [q.method for q in calls] == ['GET']


def test_hierarchy_cycle_detected_before_write(monkeypatch):
    db = sample()
    db['assets'][1]['is_group'] = True
    api, _, calls = build_api(db)
    patched_api(monkeypatch, api)
    with pytest.raises(ValueError, match='Zyklische'):
        hier.v21_bulk_set_parent('assets', json.dumps([
            {'record_id': A, 'parent_id': B}, {'record_id': B, 'parent_id': A}
        ]), execute=True)
    assert {q.method for q in calls} == {'GET'}


def test_parent_must_be_group_and_reparent_forbidden(monkeypatch):
    api, _, calls = build_api()
    patched_api(monkeypatch, api)
    with pytest.raises(ValueError, match='is_group'):
        hier.v21_bulk_set_parent('assets', json.dumps([{'record_id': A, 'parent_id': B}]), execute=True)
    assert {q.method for q in calls} == {'GET'}
    db = sample()
    db['assets'][2]['parent_id'] = A
    db['assets'][1]['is_group'] = True
    api2, _, calls2 = build_api(db)
    patched_api(monkeypatch, api2)
    with pytest.raises(ValueError, match='keine automatische Umhängung'):
        hier.v21_bulk_set_parent('assets', json.dumps([{'record_id': C, 'parent_id': B}]), execute=True)
    assert {q.method for q in calls2} == {'GET'}


def test_invalid_payload_and_cross_resource_forbidden(monkeypatch):
    api, _, calls = build_api()
    patched_api(monkeypatch, api)
    for resource, payload in (
        ('measures', [{'record_id': M, 'parent_id': A}]),
        ('assets', [{'record_id': B, 'parent_id': A, 'unexpected': 1}]),
        ('assets', [{'record_id': A, 'parent_id': A}]),
        ('assets', [{'record_id': B, 'parent_id': '../../other'}]),
        ('assets', [{'record_id': B, 'parent_id': A}] * 2),
    ):
        with pytest.raises(ValueError):
            hier.v21_bulk_set_parent(resource, json.dumps(payload), execute=True)
    assert calls == []


def test_successful_asset_parent_put_preserves_original_fields(monkeypatch):
    api, db, calls = build_api()
    patched_api(monkeypatch, api)
    out = hier.v21_bulk_set_parent('assets', json.dumps([{'record_id': B, 'parent_id': A}]), execute=True)
    assert out['completed'] is True
    assert db['assets'][1]['parent_id'] == A
    puts = [req for req in calls if req.method == 'PUT']
    assert len(puts) == 1
    assert json.loads(puts[0].content) == {'title': 'Server', 'parent_id': A}
    assert db['assets'][1]['asset_owner_user_id'] == 1


def test_process_parent_link_is_supported_and_verified(monkeypatch):
    db = sample()
    parent = 'parent_process_01'
    db['business-processes'].append({'id': parent, 'title': 'Parent', 'parent_id': None})
    api, db, calls = build_api(db)
    patched_api(monkeypatch, api)
    out = hier.v21_bulk_set_parent('business-processes', json.dumps([
        {'record_id': P, 'parent_id': parent}
    ]), execute=True)
    assert out['completed']
    assert db['business-processes'][0]['parent_id'] == parent
    assert [r.method for r in calls].count('PUT') == 1


def test_partial_failure_stops_and_reports_without_retry(monkeypatch):
    api, _, calls = build_api(fail_put_at=C)
    patched_api(monkeypatch, api)
    out = hier.v21_bulk_set_parent('assets', json.dumps([
        {'record_id': B, 'parent_id': A}, {'record_id': C, 'parent_id': A}
    ]), execute=True)
    assert out['completed'] is False and out['stopped_at_index'] == 1
    assert len(out['results']) == 1
    assert [req.method for req in calls].count('PUT') == 2


def test_no_write_when_inventory_incomplete(monkeypatch):
    db = sample()
    db['assets'] = [deepcopy(db['assets'][0])] * 100  # triggers meta total_pages 2
    api, _, calls = build_api(db, pagination_truncated=True)
    patched_api(monkeypatch, api)
    with pytest.raises(RuntimeError, match='unvollständig'):
        hier.v21_bulk_set_parent('assets', json.dumps([{'record_id': B, 'parent_id': A}]), execute=True, max_pages=1)
    assert {req.method for req in calls} == {'GET'}


def test_register_has_five_unique_tools_and_meaningful_errors(monkeypatch):
    class MCP:
        def __init__(self): self.tools = {}
        def tool(self):
            def register(fn):
                assert fn.__name__ not in self.tools
                self.tools[fn.__name__] = fn
                return fn
            return register
    m = MCP()
    register_v21_tools(m)
    assert set(m.tools) == {fn.__name__ for fn in V21_TOOLS}
    assert len(m.tools) == 5
    for fn in V21_TOOLS:
        assert inspect.signature(m.tools[fn.__name__]) == inspect.signature(fn)
    err = m.tools['v21_bulk_set_parent']('risks', '[]')
    assert err['ok'] is False and err['error_type'] == 'validation_error'


def test_all_36_tools_register_without_collision():
    from v2_register import register_v2_tools
    class MCP:
        def __init__(self): self.names = []
        def tool(self):
            def register(fn):
                self.names.append(fn.__name__)
                return fn
            return register
    m = MCP()
    register_v2_tools(m)
    register_v21_tools(m)
    assert len(m.names) == 20
    assert len(set(m.names)) == 20
    # Original 16 tools are still registered by server.py separately.


def test_existing_parent_assignment_is_idempotent(monkeypatch):
    db = sample()
    db['assets'][1]['parent_id'] = A
    api, _, calls = build_api(db)
    patched_api(monkeypatch, api)
    out = hier.v21_bulk_set_parent('assets', json.dumps([{'record_id': B, 'parent_id': A}]), execute=True)
    assert out['completed'] and out['results'][0]['updated'] is False
    assert [q.method for q in calls] == ['GET']


def test_archive_and_missing_references_block_parenting(monkeypatch):
    db = sample()
    db['assets'][0]['is_archived'] = True
    api, _, calls = build_api(db)
    patched_api(monkeypatch, api)
    with pytest.raises(ValueError, match='Archivierte'):
        hier.v21_bulk_set_parent('assets', json.dumps([{'record_id': B, 'parent_id': A}]), execute=True)
    assert not any(q.method == 'PUT' for q in calls)
    api2, _, calls2 = build_api()
    patched_api(monkeypatch, api2)
    with pytest.raises(ValueError, match='nicht in der vollständigen'):
        hier.v21_bulk_set_parent('assets', json.dumps([
            {'record_id': '00000000-0000-0000-0000-000000000000', 'parent_id': A}
        ]), execute=True)
    assert not any(q.method == 'PUT' for q in calls2)


def test_missing_asset_direction_is_not_guessed():
    db = sample()
    db['assets'][0]['linked_assets'][0].pop('direction')
    db['assets'][1]['linked_assets'].clear()
    api, _, _ = build_api(db)
    out = rel.build_relationship_graph(api)
    assert not any(e['relation'] == 'asset_relation:depends_on' for e in out['edges'])


def test_put_failure_reports_unknown_outcome_without_retry(monkeypatch):
    api, _, calls = build_api(fail_after_update=True)
    patched_api(monkeypatch, api)
    out = hier.v21_bulk_set_parent('assets', json.dumps([{'record_id': B, 'parent_id': A}]), execute=True)
    assert out['completed'] is False and out['stopped_at_index'] == 0
    assert out['results'] == []
    assert [q.method for q in calls].count('PUT') == 1
    assert 'Teilerfolg' in out['note']


def test_legacy_31_tools_plus_v21_are_36(monkeypatch):
    import importlib
    import sys
    import types

    class StubMCP:
        def __init__(self, name):
            self.names = []
        def tool(self):
            def register(fn):
                self.names.append(fn.__name__)
                return fn
            return register
        def run(self, **kw):
            pytest.fail('Not permitted to start stdio in tests')

    pkg = types.ModuleType('mcp')
    pkg.__path__ = []
    sdk = types.ModuleType('mcp.server')
    sdk.MCPServer = StubMCP
    monkeypatch.setitem(sys.modules, 'mcp', pkg)
    monkeypatch.setitem(sys.modules, 'mcp.server', sdk)
    monkeypatch.delitem(sys.modules, 'server', raising=False)
    server = importlib.import_module("server")

    if len(server.mcp.names) == 16:
        from v2_register import register_v2_tools
        register_v2_tools(server.mcp)

    if len(server.mcp.names) == 31:
        register_v21_tools(server.mcp)

    assert len(server.mcp.names) in (36, 47)
    assert {fn.__name__ for fn in V21_TOOLS}.issubset(
        set(server.mcp.names)
    )
    assert len(set(server.mcp.names)) == len(server.mcp.names)
    monkeypatch.delitem(sys.modules, 'server', raising=False)
