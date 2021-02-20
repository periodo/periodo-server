import httpx
import pytest
from urllib.parse import urlparse
from periodo import DEV_SERVER_NAME


@pytest.mark.client_auth_token('this-token-has-admin-permissions')
def test_put_graph(admin_identity, client, load_json):
    id = 'places/us-states'
    res = client.put(f'/graphs/{id}', json=load_json('test-graph.json'))
    assert res.status_code == httpx.codes.CREATED
    graph_url = urlparse(res.headers['Location'])
    assert f'/graphs/{id}' == graph_url.path
    assert 'version=0' == graph_url.query
    res = client.get(res.headers['Location'])
    assert 'Last-Modified' in res.headers
    assert res.headers['Etag'] == 'W/"graph-places/us-states-version-0"'
    res = client.get('/graphs/')
    assert res.status_code == httpx.codes.OK
    assert (
        {f'http://{DEV_SERVER_NAME}/d/',
         f'http://{DEV_SERVER_NAME}/graphs/{id}'}
        == set(res.json()['graphs'].keys())
    )


@pytest.mark.client_auth_token('this-token-has-admin-permissions')
def test_if_none_match(admin_identity, client, load_json):
    id = 'places/us-states'
    res = client.put(f'/graphs/{id}', json=load_json('test-graph.json'))
    res = client.get(
        res.headers['Location'],
        headers={
            'If-None-Match':
            'W/"graph-places/us-states-version-0"'})
    assert res.status_code == httpx.codes.NOT_MODIFIED


@pytest.mark.client_auth_token('this-token-has-normal-permissions')
def test_put_graph_requires_permission(active_identity, client, load_json):
    id = 'places/us-states'
    res = client.put(f'/graphs/{id}', json=load_json('test-graph.json'))
    assert res.status_code == httpx.codes.FORBIDDEN


def test_delete_graph_requires_auth(
        admin_identity,
        client,
        load_json,
        bearer_auth
):
    id = 'places/us-states'
    res = client.put(
        f'/graphs/{id}',
        json=load_json('test-graph.json'),
        auth=bearer_auth('this-token-has-admin-permissions')
    )
    res = client.delete(f'/graphs/{id}')
    assert res.status_code == httpx.codes.UNAUTHORIZED


@pytest.mark.client_auth_token('this-token-has-admin-permissions')
def test_update_graph(admin_identity, client, load_json):
    id = 'places/us-states'
    res = client.put(f'/graphs/{id}', json=load_json('test-graph.json'))
    graph_url_v0 = urlparse(res.headers['Location'])
    assert f'/graphs/{id}' == graph_url_v0.path
    assert 'version=0' == graph_url_v0.query

    res = client.put(f'/graphs/{id}', json=load_json('test-graph-updated.json'))
    assert res.status_code == httpx.codes.CREATED
    graph_url_v1 = urlparse(res.headers['Location'])
    assert f'/graphs/{id}' == graph_url_v1.path
    assert 'version=1' == graph_url_v1.query

    res = client.get(f'/graphs/{id}')
    data = res.json()
    assert len(data['graphs']) == 1
    assert (
        data['graphs']
        [f'http://{DEV_SERVER_NAME}/graphs/{id}']
        ['features'][0]['names'][0]['toponym']
        == 'Minnesooooooota'
    )
    assert (
        res.headers['Content-Disposition']
        == 'attachment; filename="periodo-graph-places-us-states.json"'
    )

    res = client.get(f'/graphs/{id}?version=0')
    data = res.json()
    assert len(data['graphs']) == 1
    assert (
        data['graphs']
        [f'http://{DEV_SERVER_NAME}/graphs/{id}?version=0']
        ['features'][0]['names'][0]['toponym']
        == 'Minnesota'
    )
    assert (
        res.headers['Content-Disposition']
        == 'attachment; filename="periodo-graph-places-us-states-v0.json"'
    )

    res = client.get(f'/graphs/{id}?version=1')
    data = res.json()
    assert len(data['graphs']) == 1
    assert (
        data['graphs']
        [f'http://{DEV_SERVER_NAME}/graphs/{id}?version=1']
        ['features'][0]['names'][0]['toponym']
        == 'Minnesooooooota'
    )
    assert (
        data['graphs']
        [f'http://{DEV_SERVER_NAME}/graphs/{id}?version=1']
        ['wasRevisionOf']
        == f'http://{DEV_SERVER_NAME}/graphs/{id}?version=0')
    assert (
        res.headers['Content-Disposition']
        == 'attachment; filename="periodo-graph-places-us-states-v1.json"'
    )


@pytest.mark.client_auth_token('this-token-has-admin-permissions')
def test_delete_graph(admin_identity, client, load_json):
    id = 'places/us-states'
    res = client.put(f'/graphs/{id}', json=load_json('test-graph.json'))
    res = client.delete(f'/graphs/{id}')
    assert res.status_code == httpx.codes.NO_CONTENT
    res = client.get(f'/graphs/{id}')
    assert res.status_code == httpx.codes.NOT_FOUND
    res = client.get('/graphs/%s?version=0' % id)
    assert res.status_code == httpx.codes.OK
    res = client.get('/graphs/')
    assert res.status_code == httpx.codes.OK
    data = res.json()
    assert {f'http://{DEV_SERVER_NAME}/d/'} == set(data['graphs'].keys())
    res = client.put(f'/graphs/{id}', json=load_json('test-graph.json'))
    assert res.status_code == httpx.codes.CREATED
    graph_url_v1 = urlparse(res.headers['Location'])
    assert f'/graphs/{id}' == graph_url_v1.path
    assert 'version=1' == graph_url_v1.query
    res = client.get(f'/graphs/{id}')
    assert res.status_code == httpx.codes.OK
    res = client.get(f'/graphs/{id}?version=0')
    assert res.status_code == httpx.codes.OK
    res = client.get(f'/graphs/{id}?version=1')
    assert res.status_code == httpx.codes.OK


@pytest.mark.client_auth_token('this-token-has-admin-permissions')
def test_group_sibling_graphs(admin_identity, client, load_json):
    graph_json = load_json('test-graph.json')
    res = client.put('/graphs/places/A', json=graph_json)
    res = client.put('/graphs/places/B', json=graph_json)
    res = client.put('/graphs/not-places/C', json=graph_json)

    res = client.get('/graphs/places/')
    assert res.status_code == httpx.codes.OK
    data = res.json()
    assert (
        {f'http://{DEV_SERVER_NAME}/graphs/places/A',
         f'http://{DEV_SERVER_NAME}/graphs/places/B'}
        == set(data['graphs'].keys())
    )
    assert (
        f'http://{DEV_SERVER_NAME}/graphs/places/'
        == data['@context']['graphs']['@id']
    )

    res = client.get('/graphs/places.json')
    assert res.status_code == httpx.codes.OK
    data = res.json()
    assert (
        {f'http://{DEV_SERVER_NAME}/graphs/places/A',
         f'http://{DEV_SERVER_NAME}/graphs/places/B'}
        == set(data['graphs'].keys())
    )
    assert (
        f'http://{DEV_SERVER_NAME}/graphs/places/'
        == data['@context']['graphs']['@id']
    )

    res = client.get('/graphs/places')
    assert res.status_code == httpx.codes.OK
    data = res.json()
    assert (
        {f'http://{DEV_SERVER_NAME}/graphs/places/A',
         f'http://{DEV_SERVER_NAME}/graphs/places/B'}
        == set(data['graphs'].keys())
    )
    assert (
        f'http://{DEV_SERVER_NAME}/graphs/places/'
        == data['@context']['graphs']['@id']
    )
    assert (
        res.headers['Content-Disposition']
        == 'attachment; filename="periodo-graph-places.json"'
    )

    res = client.get('/graphs/')
    assert res.status_code == httpx.codes.OK
    data = res.json()
    assert (
        {f'http://{DEV_SERVER_NAME}/graphs/places/A',
         f'http://{DEV_SERVER_NAME}/graphs/places/B',
         f'http://{DEV_SERVER_NAME}/graphs/not-places/C',
         f'http://{DEV_SERVER_NAME}/d/'}
        == set(data['graphs'].keys())
    )
    assert (
        f'http://{DEV_SERVER_NAME}/graphs/'
        == data['@context']['graphs']['@id']
    )
    assert (
        res.headers['Content-Disposition']
        == 'attachment; filename="periodo-graphs.json"'
    )
