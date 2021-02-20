import httpx
import json
import pytest
import re
from rdflib import ConjunctiveGraph
from rdflib.namespace import Namespace
from urllib.parse import urlparse
from periodo import app, database, identifier, cache, DEV_SERVER_NAME

PERIODO = Namespace('http://n2t.net/ark:/99152/')
PROV = Namespace('http://www.w3.org/ns/prov#')
HOST = Namespace(f'http://{DEV_SERVER_NAME}/')


def test_initial_data_load_patch(init_db):
    with app.app_context():
        created_entities = json.loads(database.query_db(
            'SELECT created_entities FROM patch_request WHERE id = 1',
            one=True)['created_entities'])
        assert (
            created_entities
            == ['p0trgkv', 'p0trgkv4kxb', 'p0trgkvkhrv', 'p0trgkvwbjd']
        )
        updated_entities = json.loads(database.query_db(
            'SELECT updated_entities FROM patch_request WHERE id = 1',
            one=True)['updated_entities'])
        assert updated_entities == []


@pytest.mark.client_auth_token('this-token-has-normal-permissions')
def test_submit_patch(active_identity, client, load_json):
    res = client.patch(
        '/d/',
        json=load_json('test-patch-replace-values-1.json')
    )
    assert res.status_code == httpx.codes.ACCEPTED
    patch_id = int(res.headers['Location'].split('/')[-2])
    with app.app_context():
        updated_entities = json.loads(database.query_db(
            'SELECT updated_entities FROM patch_request WHERE id = ?',
            (patch_id,), one=True)['updated_entities'])
        assert updated_entities == ['p0trgkv', 'p0trgkvwbjd']
        created_entities = json.loads(database.query_db(
            'SELECT created_entities FROM patch_request WHERE id = ?',
            (patch_id,), one=True)['created_entities'])
        assert created_entities == []


@pytest.mark.client_auth_token('this-token-has-normal-permissions')
def test_update_patch(active_identity, client, load_json):
    patch1 = load_json('test-patch-replace-values-1.json')
    res = client.patch('/d/', json=patch1)
    patch_url = urlparse(res.headers['Location']).path
    jsonpatch_url = patch_url + 'patch.jsonpatch'
    res = client.get(jsonpatch_url)
    assert res.json() == patch1

    patch2 = load_json('test-patch-replace-values-2.json')
    res = client.put(jsonpatch_url, json=patch2)
    assert res.status_code == httpx.codes.OK
    res = client.get(jsonpatch_url)
    assert res.json() == patch2


@pytest.mark.client_auth_token('this-token-has-normal-permissions')
def test_merge_patch(
        active_identity,
        admin_identity,
        client,
        bearer_auth,
        load_json
):
    res = client.patch('/d/', json=load_json('test-patch-adds-items.json'))
    patch_id = int(res.headers['Location'].split('/')[-2])
    with app.app_context():
        updated_entities = json.loads(database.query_db(
            'SELECT updated_entities FROM patch_request WHERE id = ?',
            (patch_id,), one=True)['updated_entities'])
        assert updated_entities == ['p0trgkv']
        created_entities = json.loads(database.query_db(
            'SELECT created_entities FROM patch_request WHERE id = ?',
            (patch_id,), one=True)['created_entities'])
        # unmerged patch may have updated entities, but never created entities
        assert created_entities == []

        patch_url = urlparse(res.headers['Location']).path
        res = client.post(
            patch_url + 'merge',
            auth=bearer_auth('this-token-has-admin-permissions')
        )
        assert res.status_code == httpx.codes.NO_CONTENT
        row = database.query_db(
            'SELECT applied_to, resulted_in FROM patch_request WHERE id=?',
            (patch_id,), one=True)
        assert row['applied_to'] == 1
        assert row['resulted_in'] == 2
        updated_entities = json.loads(database.query_db(
            'SELECT updated_entities FROM patch_request WHERE id = ?',
            (patch_id,), one=True)['updated_entities'])
        assert updated_entities == ['p0trgkv']  # same as before
        created_entities = json.loads(database.query_db(
            'SELECT created_entities FROM patch_request WHERE id = ?',
            (patch_id,), one=True)['created_entities'])
        # after merge we can see the created entities
        assert 4 == len(created_entities)
        for entity_id in created_entities:
            assert re.match(identifier.IDENTIFIER_RE, entity_id)

    # submitting the same patch and trying to merge it again should fail
    res = client.patch('/d/', json=load_json('test-patch-adds-items.json'))
    patch_url = urlparse(res.headers['Location']).path
    res = client.post(
        patch_url + 'merge',
        auth=bearer_auth('this-token-has-admin-permissions')
    )
    assert res.status_code == httpx.codes.BAD_REQUEST


@pytest.mark.client_auth_token('this-token-has-normal-permissions')
def test_reject_patch(
        active_identity,
        admin_identity,
        client,
        bearer_auth,
        load_json
):
    res = client.patch('/d/', json=load_json('test-patch-adds-items.json'))
    patch_id = int(res.headers['Location'].split('/')[-2])
    patch_url = urlparse(res.headers['Location']).path
    res = client.post(
        patch_url + 'reject',
        auth=bearer_auth('this-token-has-admin-permissions')
    )
    assert res.status_code == httpx.codes.NO_CONTENT
    with app.app_context():
        row = database.query_db(
            'SELECT open, merged FROM patch_request WHERE id=?',
            (patch_id,), one=True)

        assert row['open'] == 0
        assert row['merged'] == 0


@pytest.mark.client_auth_token('this-token-has-normal-permissions')
def test_comment_on_patch(active_identity, client, load_json):
    res = client.patch('/d/', json=load_json('test-patch-adds-items.json'))
    patch_id = int(res.headers['Location'].split('/')[-2])
    patch_url = urlparse(res.headers['Location']).path
    res = client.post(patch_url + 'messages', json={'message': 'a comment'})
    assert res.status_code == httpx.codes.OK
    assert urlparse(res.headers['Location']).path == patch_url
    with app.app_context():
        row = database.query_db(
            'SELECT * FROM patch_request_comment WHERE patch_request_id=?',
            (patch_id,), one=True)
        assert row['author'] == 'https://orcid.org/1234-5678-9101-112X'
        assert row['patch_request_id'] == patch_id
        assert row['message'] == 'a comment'

        res = client.get(patch_url)
        patch = res.json()
        comments = patch.get('comments')
        assert len(comments) == 1
        assert patch['first_comment'] == 'a comment'


def test_versioning(client, submit_and_merge_patch):

    submit_and_merge_patch('test-patch-adds-items.json')
    submit_and_merge_patch('test-patch-add-period.json')

    res = client.get('/trgkv.json', params={'version': 0})
    assert res.status_code == httpx.codes.NOT_FOUND

    for version in range(1, 4):
        res = client.get(
            '/trgkv',
            params={'version': version},
            headers={'Accept': 'application/json'},
            allow_redirects=False,
        )
        assert res.status_code == httpx.codes.SEE_OTHER
        assert (
            '/' + res.headers['Location'].split('/')[-1]
            == f'/trgkv.json?version={version}'
        )
        res = client.get(
            '/trgkv.json',
            params={'version': version},
        )
        assert res.status_code == httpx.codes.OK
        assert res.headers['Content-Type'] == 'application/json'
        ctx = res.json()['@context']
        assert (
            ctx[0] == f'http://{DEV_SERVER_NAME}/c?version={version}'
        )
        res = client.get('/history.nt')
        assert res.headers['Cache-Control'] == 'public, max-age=0'
        assert res.headers['X-Accel-Expires'] == f'{cache.MEDIUM_TIME}'


def test_context_versioning(client, submit_and_merge_patch):

    submit_and_merge_patch('test-patch-modify-context.json')

    res = client.get('/d.json', params={'version': 0})
    assert res.status_code == httpx.codes.OK
    ctx = res.json().get('@context', None)
    assert ctx is None

    res = client.get('/c', params={'version': 0})
    assert res.status_code == httpx.codes.NOT_FOUND

    res = client.get('/d.json', params={'version': 1})
    assert res.status_code == httpx.codes.OK
    assert res.headers['Cache-Control'] == f'public, max-age={cache.LONG_TIME}'
    ctx = res.json()['@context']
    assert ctx[0] == f'http://{DEV_SERVER_NAME}/c?version=1'

    res = client.get('/c', params={'version': 1})
    assert res.status_code == httpx.codes.OK
    assert res.headers['Cache-Control'] == f'public, max-age={cache.LONG_TIME}'
    ctx = res.json()['@context']
    assert 'foobar' not in ctx

    res = client.get('/d.json', params={'version': 2})
    assert res.status_code == httpx.codes.OK
    ctx = res.json()['@context']
    assert ctx[0] == f'http://{DEV_SERVER_NAME}/c?version=2'

    res = client.get('/c', params={'version': 2})
    assert res.status_code == httpx.codes.OK
    ctx = res.json()['@context']
    assert 'foobar' in ctx


def test_remove_period(client, submit_and_merge_patch):

    submit_and_merge_patch('test-patch-remove-period.json')

    with app.app_context():
        removed_entities = database.get_removed_entity_keys()
        assert removed_entities == set(['p0trgkvwbjd'])

    res = client.get('/trgkvwbjd.json')
    assert res.status_code == httpx.codes.GONE

    res = client.get(
        '/trgkvwbjd.json',
        params={'version': 0},
    )
    assert res.status_code == httpx.codes.NOT_FOUND

    res = client.get(
        '/trgkvwbjd.json',
        params={'version': 1},
    )
    assert res.status_code == httpx.codes.OK

    res = client.get('/history.nt')
    g = ConjunctiveGraph()
    g.parse(format='nt', data=res.text)

    generated = list(g.objects(
        subject=HOST['h#change-2'],
        predicate=PROV.generated
    ))
    assert len(generated) == 1
    assert HOST['d?version=2'] in generated


def test_remove_authority(client, submit_and_merge_patch):

    submit_and_merge_patch('test-patch-remove-authority.json')

    with app.app_context():
        removed_entities = database.get_removed_entity_keys()
        assert removed_entities == set(
            ['p0trgkv', 'p0trgkv4kxb', 'p0trgkvkhrv', 'p0trgkvwbjd']
        )

    res = client.get('/trgkv.json')
    assert res.status_code == httpx.codes.GONE

    res = client.get(
        '/trgkv.json',
        params={'version': 0},
    )
    assert res.status_code == httpx.codes.NOT_FOUND

    res = client.get(
        '/trgkv.json',
        params={'version': 1},
    )
    assert res.status_code == httpx.codes.OK

    res = client.get('/trgkvwbjd.json')
    assert res.status_code == httpx.codes.GONE

    res = client.get(
        '/trgkvwbjd.json',
        params={'version': 0},
    )
    assert res.status_code == httpx.codes.NOT_FOUND

    res = client.get(
        '/trgkvwbjd.json',
        params={'version': 1},
    )
    assert res.status_code == httpx.codes.OK

    res = client.get('/h.nt')
    g = ConjunctiveGraph()
    g.parse(format='nt', data=res.text)

    generated = g.value(
        subject=HOST['h#change-2'],
        predicate=PROV.generated,
        any=False
    )
    assert generated == HOST['d?version=2']
