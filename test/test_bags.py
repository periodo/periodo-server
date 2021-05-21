import httpx
import pytest
from rdflib.namespace import Namespace
from urllib.parse import urlparse
from uuid import UUID
from periodo import DEV_SERVER_NAME

PERIODO = Namespace("http://n2t.net/ark:/99152/")
PROV = Namespace("http://www.w3.org/ns/prov#")


@pytest.mark.client_auth_token("this-token-has-normal-permissions")
def test_create_bag(active_user, client, load_json):
    active_user
    id = UUID("6f2c64e2-c65f-4e2d-b028-f89dfb71ce69")
    res = client.put(f"/bags/{id}", json=load_json("test-bag.json"))
    assert res.status_code == httpx.codes.CREATED
    bag_url = urlparse(res.headers["Location"])
    assert bag_url.path == f"/bags/{id}"
    assert bag_url.query == "version=0"
    res = client.get(res.headers["Location"])
    assert "Last-Modified" in res.headers
    assert res.headers["Etag"] == (
        'W/"bag-6f2c64e2-c65f-4e2d-b028-f89dfb71ce69-version-0"'
    )
    jsonld = res.json()
    assert jsonld == load_json("test-bag.jsonld")
    assert jsonld["@context"] == [
        f"http://{DEV_SERVER_NAME}/c",
        {"@base": "http://n2t.net/ark:/99152/"},
    ]
    res = client.get("/bags/")
    assert res.status_code == httpx.codes.OK
    assert res.headers["Content-Type"] == "application/json"
    assert res.json() == [f"http://{DEV_SERVER_NAME}/bags/{id}"]


@pytest.mark.client_auth_token("this-token-has-normal-permissions")
def test_if_none_match(active_user, client, load_json):
    active_user
    id = UUID("6f2c64e2-c65f-4e2d-b028-f89dfb71ce69")
    res = client.put(f"/bags/{id}", json=load_json("test-bag.json"))
    assert res.status_code == httpx.codes.CREATED
    res = client.get(
        res.headers["Location"],
        headers={
            "If-None-Match": 'W/"bag-6f2c64e2-c65f-4e2d-b028-f89dfb71ce69-version-0"'
        },
    )
    assert res.status_code == httpx.codes.NOT_MODIFIED


def test_create_bag_requires_auth(client, load_json):
    id = UUID("6f2c64e2-c65f-4e2d-b028-f89dfb71ce69")
    res = client.put(f"/bags/{id}", json=load_json("test-bag.json"))
    assert res.status_code == httpx.codes.UNAUTHORIZED


@pytest.mark.client_auth_token("this-token-has-normal-permissions")
def test_create_bag_requires_title(active_user, client, load_json):
    active_user
    id = UUID("6f2c64e2-c65f-4e2d-b028-f89dfb71ce69")
    bag_json = load_json("test-bag.json")
    del bag_json["title"]
    res = client.put(f"/bags/{id}", json=bag_json)
    assert res.status_code == httpx.codes.BAD_REQUEST
    assert res.json()["message"] == "A bag must have a title"


@pytest.mark.client_auth_token("this-token-has-normal-permissions")
def test_create_bag_requires_items_array(active_user, client, load_json):
    active_user
    id = UUID("6f2c64e2-c65f-4e2d-b028-f89dfb71ce69")
    bag_json = load_json("test-bag.json")
    del bag_json["items"]
    res = client.put(f"/bags/{id}", json=bag_json)
    assert res.status_code == httpx.codes.BAD_REQUEST
    assert res.json()["message"] == "A bag must have at least two items"


@pytest.mark.client_auth_token("this-token-has-normal-permissions")
def test_create_bag_requires_minimum_of_two_items(active_user, client, load_json):
    active_user
    id = UUID("6f2c64e2-c65f-4e2d-b028-f89dfb71ce69")
    bag_json = load_json("test-bag.json")
    bag_json["items"].pop()
    res = client.put(f"/bags/{id}", json=bag_json)
    assert res.status_code == httpx.codes.BAD_REQUEST
    assert res.json()["message"] == "A bag must have at least two items"


@pytest.mark.client_auth_token("this-token-has-normal-permissions")
def test_create_bag_requires_items_be_periodo_ids(active_user, client, load_json):
    active_user
    id = UUID("6f2c64e2-c65f-4e2d-b028-f89dfb71ce69")
    bag_json = load_json("test-bag.json")
    bag_json["items"].append("foobar")
    res = client.put(f"/bags/{id}", json=bag_json)
    assert res.status_code == httpx.codes.BAD_REQUEST
    assert res.json()["message"] == "No resource with key: foobar"


@pytest.mark.client_auth_token("this-token-has-normal-permissions")
def test_update_bag(active_user, client, load_json):
    active_user
    id = UUID("6f2c64e2-c65f-4e2d-b028-f89dfb71ce69")
    res = client.put(f"/bags/{id}", json=load_json("test-bag.json"))
    assert res.status_code == httpx.codes.CREATED
    bag_url_v0 = urlparse(res.headers["Location"])
    assert f"/bags/{id}" == bag_url_v0.path
    assert "version=0" == bag_url_v0.query
    res = client.put(f"/bags/{id}", json=load_json("test-bag-updated.json"))
    assert res.status_code == httpx.codes.CREATED
    bag_url_v1 = urlparse(res.headers["Location"])
    assert f"/bags/{id}" == bag_url_v1.path
    assert "version=1" == bag_url_v1.query
    res = client.get(f"/bags/{id}")
    assert res.json() == load_json("test-bag-updated.jsonld")
    res = client.get(f"/bags/{id}?version=0")
    assert res.json() == load_json("test-bag.jsonld")
    res = client.get(f"/bags/{id}?version=1")
    assert res.json() == load_json("test-bag-updated.jsonld")


@pytest.mark.client_auth_token("this-token-has-normal-permissions")
def test_create_bag_using_jsonld(active_user, client, load_json):
    active_user
    id = UUID("6f2c64e2-c65f-4e2d-b028-f89dfb71ce69")
    res = client.put(f"/bags/{id}", json=load_json("test-bag.json"))
    res = client.put(f"/bags/{id}", json=load_json("test-bag-updated.jsonld"))
    assert res.status_code == httpx.codes.CREATED
    res = client.get(f"/bags/{id}")
    assert res.json() == load_json("test-bag-updated.jsonld")
    res = client.get(f"/bags/{id}?version=0")
    assert res.json() == load_json("test-bag.jsonld")
    res = client.get(f"/bags/{id}?version=1")
    assert res.json() == load_json("test-bag-updated.jsonld")


@pytest.mark.client_auth_token("this-token-has-normal-permissions")
def test_update_bag_must_be_owner(
    active_user, admin_user, client, bearer_auth, load_json
):
    active_user, admin_user
    id = UUID("6f2c64e2-c65f-4e2d-b028-f89dfb71ce69")
    res = client.put(f"/bags/{id}", json=load_json("test-bag.json"))
    res = client.put(
        f"/bags/{id}",
        json=load_json("test-bag-updated.jsonld"),
        auth=bearer_auth("this-token-has-admin-permissions"),
    )
    assert res.status_code == httpx.codes.FORBIDDEN
