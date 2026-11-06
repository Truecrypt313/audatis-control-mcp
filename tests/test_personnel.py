"""Entirely offline: no secrets, real HTTP requests, audatis writes or stdio processes."""
from __future__ import annotations

import importlib
import json
import sys
import types

import httpx
import pytest

import personnel_tools as tools
from personnel_core import PersonnelAPI, validate_create, validate_update, ids_json
from personnel_register import PERSONNEL_TOOLS, register_personnel_tools
from v2_core import BASE


def api_with(handler):
    return PersonnelAPI("https://tenant.example.test", "READ_FAKE",
                        write_token="WRITE_FAKE", transport=httpx.MockTransport(handler))


def respond(req, data, status=200, meta=None):
    output = {"data": data}
    if meta is not None:
        output["meta"] = meta
    return httpx.Response(status, json=output)


def fake_person(pid=5, organisations=None, **kwargs):
    d = {"id": pid, "first_name": "Ada", "last_name": "Muster", "email": "ada@example.test",
         "organisation_ids": organisations or [], "status": "active", "is_archived": False,
         "employee_number": None, "language": "de"}
    return {**d, **kwargs}


def test_fields_from_openapi_validate_create_update():
    payload = {"first_name": "Max", "last_name": "Test", "email": "max@example.test",
               "organisation_ids": [3], "status": "active", "login_mode": "email"}
    assert validate_create(json.dumps(payload)) == payload
    for bad in ({"first_name": "Max", "last_name": "Test", "email": "bad"},
                {"last_name": "X", "email": "test@example.test"},
                {**payload, "admin_role": "superuser"},
                {**payload, "organisation_ids": [3, 3]},
                {**payload, "organisation_ids": [True]},
                {**payload, "elearning_ids": [99]}):
        with pytest.raises(ValueError):
            validate_create(json.dumps(bad))
    assert validate_update('{"language":"en"}') == {"language": "en"}
    with pytest.raises(ValueError):
        validate_update('{"organisation_ids":[3]}')
    with pytest.raises(ValueError):
        validate_update('{"tag_ids":["x"]}')


def test_ids_guard_positive_integer_and_duplicates():
    assert ids_json('[1,2]', 'ids') == [1, 2]
    assert ids_json('[]', 'ids', allow_empty=True) == []
    for bad in ('[true]', '[0]', '[-2]', '[1,1]', '["1"]', '{}', '[]'):
        with pytest.raises(ValueError):
            ids_json(bad, 'ids')


def test_reads_use_fixed_tenant_and_read_token(monkeypatch):
    paths = []
    def handle(req):
        assert req.method == "GET"
        assert req.headers["Authorization"] == "Bearer READ_FAKE"
        paths.append(req.url.path)
        if req.url.path.endswith("/organisations"):
            return respond(req, [{"id": 3, "name": "IT", "parent_id": None, "level": 1}], meta={"total_pages": 1})
        if req.url.path.endswith("/organisations/3"):
            return respond(req, {"id": 3, "name": "IT", "parent_id": None, "level": 1})
        if req.url.path.endswith("/personal"):
            return respond(req, [fake_person()], meta={"total_pages": 1})
        if req.url.path.endswith("/personal/5"):
            return respond(req, fake_person())
        if req.url.path.endswith("/users/7"):
            return respond(req, {"id": 7, "name": "A. Test"})
        if req.url.path.endswith("/personal/tags"):
            return respond(req, [{"id": "tag", "name": "MFA", "is_visible": True}], meta={"total_pages": 1})
        if req.url.path.endswith("/personal/5/assignments"):
            return respond(req, {"elearning": [], "certificates": []})
        pytest.fail(req.url.path)
    api = api_with(handle)
    monkeypatch.setattr(tools.PersonnelAPI, 'from_env', staticmethod(lambda: api))
    assert tools.list_organisations()['data'][0]['name'] == 'IT'
    assert tools.get_organisation(3)['data']['id'] == 3
    assert tools.list_personnel()['data'][0]['email'] == 'ada@example.test'
    assert tools.get_personnel(5)['data']['id'] == 5
    assert tools.get_user(7)['data']['name'] == 'A. Test'
    assert tools.list_personnel_tags()['data'][0]['name'] == 'MFA'
    assert tools.get_personnel_assignments(5)['data'] == {"elearning": [], "certificates": []}
    assert len(paths) == 7
    assert all(p.startswith(BASE + '/') for p in paths)


def test_invalid_paths_and_page_limits_do_not_request():
    api = api_with(lambda req: pytest.fail("no network for bad arguments"))
    for bad in (-1, 0, True, '1', 2**40):
        with pytest.raises(ValueError): api.organisation(bad)
    with pytest.raises(ValueError): api.persons(page=0)
    with pytest.raises(ValueError): api.persons(per_page=201)
    with pytest.raises(ValueError): api.persons(archived="maybe")
    with pytest.raises(ValueError): api.persons(organisation_id=-5)


def test_create_preview_is_offline_and_no_write(monkeypatch):
    monkeypatch.setattr(tools.PersonnelAPI, 'from_env', staticmethod(
        lambda: pytest.fail('Preview must not instantiate live client')))
    out = tools.create_personnel('{"first_name":"Max","last_name":"Muster","email":"max@example.test"}')
    assert out['will_write'] is False
    assert out['fields']['email'] == 'max@example.test'


def test_create_calls_exact_post_path_and_write_token(monkeypatch):
    calls=[]
    def handle(req):
        calls.append(req)
        if req.method == 'GET' and req.url.path.endswith('/organisations/3'):
            return respond(req, {'id':3, 'name':'IT'})
        if req.method == 'GET' and req.url.path.endswith('/personal'):
            assert req.url.params.get('archived') == 'all'
            return respond(req, [], meta={'total_pages':1, 'total':0})
        if req.method == 'POST':
            assert req.url.path == BASE + '/personal'
            assert req.headers['Authorization'] == 'Bearer WRITE_FAKE'
            assert json.loads(req.content)['organisation_ids'] == [3]
            return respond(req, fake_person(9, [3]), status=201)
        pytest.fail(req.url.path)
    api=api_with(handle)
    monkeypatch.setattr(tools.PersonnelAPI, 'from_env', staticmethod(lambda:api))
    out=tools.create_personnel('{"first_name":"Ada","last_name":"Muster","email":"ada@example.test","organisation_ids":[3]}',execute=True)
    assert out['created'] is True
    assert out['data']['id'] == 9
    assert [x.method for x in calls] == ['GET','GET','POST']


def test_create_duplicate_email_blocks_post(monkeypatch):
    seen=[]
    def handle(req):
        seen.append(req.method)
        assert req.method=='GET'
        return respond(req,[fake_person(21, email="ada@example.test")],meta={'total_pages':1})
    api=api_with(handle)
    monkeypatch.setattr(tools.PersonnelAPI,'from_env',staticmethod(lambda:api))
    result=tools.create_personnel('{"first_name":"Ada","last_name":"Muster","email":"ada@example.test"}',execute=True)
    assert result['created'] is False and result['existing_ids']==[21]
    assert seen == ['GET']


def test_duplicate_check_incomplete_fails_closed():
    api=api_with(lambda req: respond(req, [], meta={'total_pages':11}))
    with pytest.raises(RuntimeError,match='unvollständig'):
        api.existing_email('test@example.test')


def test_update_preview_and_only_required_preserved(monkeypatch):
    calls=[]
    def handle(req):
        calls.append(req)
        return respond(req, fake_person())
    api=api_with(handle)
    monkeypatch.setattr(tools.PersonnelAPI,'from_env',staticmethod(lambda:api))
    out=tools.update_personnel(5,'{"language":"en"}',execute=False)
    assert out['changes']=={'language':'en'}
    assert [r.method for r in calls]==['GET']


def test_update_write_only_identity_and_change(monkeypatch):
    calls=[]
    def handle(req):
        calls.append(req)
        if req.method=='GET':return respond(req,fake_person(5,organisations=[3]))
        assert req.method=='PUT'
        assert req.headers['Authorization']=='Bearer WRITE_FAKE'
        assert req.url.path == BASE+'/personal/5'
        assert json.loads(req.content)=={
            'first_name':'Ada','last_name':'Muster','email':'ada@example.test','language':'en'}
        return respond(req,fake_person(5,organisations=[3],language='en'))
    api=api_with(handle)
    monkeypatch.setattr(tools.PersonnelAPI,'from_env',staticmethod(lambda:api))
    out=tools.update_personnel(5,'{"language":"en"}',execute=True)
    assert out['updated'] is True
    assert out['data']['organisation_ids'] == [3]
    assert [r.method for r in calls]==['GET','PUT']


def test_archived_person_cannot_update(monkeypatch):
    api=api_with(lambda req: respond(req,fake_person(is_archived=True)))
    monkeypatch.setattr(tools.PersonnelAPI,'from_env',staticmethod(lambda:api))
    with pytest.raises(ValueError,match='Archivierte'):
        tools.update_personnel(5,'{"language":"en"}',execute=True)


def test_organisation_assignment_preview_and_write(monkeypatch):
    calls=[]
    def handle(req):
        calls.append(req)
        path=req.url.path
        if path.endswith('/organisations/3'):return respond(req,{'id':3,'name':'IT'})
        if path.endswith('/personal/5'):return respond(req,fake_person(5,organisations=[1]))
        if path.endswith('/personal/6'):return respond(req,fake_person(6,organisations=[3]))
        if path.endswith('/personal/bulk-organisations'):
            assert req.method=='POST'
            assert req.headers['Authorization']=='Bearer WRITE_FAKE'
            assert json.loads(req.content)=={'person_ids':[5,6],'add':[3],'remove':[]}
            return respond(req,{'summary':{'updated':1,'unchanged':1,'not_found':0,'archived':0},
                              'results':[{'person_id':5,'result':'updated'}, {'person_id':6,'result':'unchanged'}]})
        pytest.fail(path)
    api=api_with(handle)
    monkeypatch.setattr(tools.PersonnelAPI,'from_env',staticmethod(lambda:api))
    prev=tools.assign_personnel_organisations('[5,6]','[3]','[]',execute=False)
    assert prev['changed_count']==1
    assert prev['changes'][5]['after']==[1,3]
    assert len(calls)==3 and all(r.method=='GET' for r in calls)
    done=tools.assign_personnel_organisations('[5,6]','[3]','[]',execute=True)
    assert done['completed'] is True
    assert [r.method for r in calls][-1]=='POST'


def test_bulk_validation_and_fail_closed(monkeypatch):
    monkeypatch.setattr(tools.PersonnelAPI,'from_env',staticmethod(
        lambda: pytest.fail('Invalid bulk input must not do HTTP')))
    for args in [('[5]','[]','[]'), ('[5]','[3]','[3]'), ('[5,5]','[3]','[]'),
                 ('[0]','[3]','[]'),('['+','.join(str(n) for n in range(1,27))+']','[3]','[]')]:
        with pytest.raises(ValueError):tools.assign_personnel_organisations(*args)


def test_bulk_archive_person_blocks_all_writes(monkeypatch):
    def handle(req):
        if req.url.path.endswith('/organisations/3'):return respond(req,{'id':3,'name':'IT'})
        if req.url.path.endswith('/personal/5'):return respond(req,fake_person(is_archived=True))
        pytest.fail('No POST after archived person')
    api=api_with(handle)
    monkeypatch.setattr(tools.PersonnelAPI,'from_env',staticmethod(lambda:api))
    with pytest.raises(ValueError):tools.assign_personnel_organisations('[5]','[3]','[]',execute=True)


def test_registry_signatures_and_unique_names():
    class Stub:
        def __init__(self):self.names=[]
        def tool(self):
            def registrar(fn):self.names.append(fn.__name__);return fn
            return registrar
    s=Stub()
    register_personnel_tools(s)
    assert len(s.names)==11
    assert len(set(s.names))==11
    assert not any(name.startswith(('v2_','v21_','v22_')) for name in s.names)
    assert 'create_personnel' in s.names


def test_registry_sanitizes_known_validation_errors():
    class Stub:
        def __init__(self):self.fns={}
        def tool(self):
            def registrar(fn):self.fns[fn.__name__]=fn;return fn
            return registrar
    s=Stub();register_personnel_tools(s)
    out=s.fns['create_personnel']('{"first_name":"A","last_name":"B","email":"a@example.test","unknown_field":1}')
    assert out['ok'] is False
    assert out['error_type']=='validation_error'
    assert 'unknown_field' in out['error']


def test_test_stub_mcp_full_additive_registration_has_47_tools(monkeypatch):
    # In the user's existing server.py, registration consists of 16 + 15 + 5 = 36.
    # Check that the addon is strictly additive without importing/launching actual stdio.
    class OfflineMCP:
        def __init__(self, name):self.names=[]
        def tool(self):
            def registrar(fn):self.names.append(fn.__name__);return fn
            return registrar
        def run(self, **kwargs):pytest.fail('No stdio in offline tests')
    mcp_pkg=types.ModuleType('mcp');mcp_pkg.__path__=[]
    server_pkg=types.ModuleType('mcp.server');server_pkg.MCPServer=OfflineMCP
    monkeypatch.setitem(sys.modules,'mcp',mcp_pkg)
    monkeypatch.setitem(sys.modules,'mcp.server',server_pkg)
    monkeypatch.delitem(sys.modules,'server',raising=False)
    original=importlib.import_module('server')
    from v2_register import register_v2_tools
    from v21_register import register_v21_tools
    if len(original.mcp.names)==16:register_v2_tools(original.mcp)
    if len(original.mcp.names)==31:register_v21_tools(original.mcp)
    if len(original.mcp.names) == 36:
        register_personnel_tools(original.mcp)
    assert len(original.mcp.names)==47
    assert len(set(original.mcp.names))==47
    monkeypatch.delitem(sys.modules,'server',raising=False)
