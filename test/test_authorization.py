import httpx
import json
import pytest
from urllib.parse import urlparse
from periodo import app, database


def test_unauthorized_user(unauthorized_user):
    with app.app_context():
        row = database.query_db_for_one(
            "SELECT permissions FROM user WHERE id = ?", (unauthorized_user.id,)
        )
        assert json.loads(row["permissions"]) == []


def test_admin_user(admin_user):
    with app.app_context():
        row = database.query_db_for_one(
            "SELECT permissions FROM user WHERE id = ?", (admin_user.id,)
        )
        assert json.loads(row["permissions"]) == [
            ["action", "submit-patch"],
            ["action", "create-bag"],
            ["action", "accept-patch"],
            ["action", "create-graph"],
        ]


@pytest.mark.client_auth_token("this-token-has-no-permissions")
def test_unauthorized_user_submit_patch(unauthorized_user, client):
    unauthorized_user
    res = client.patch("/d/")
    assert res.status_code == httpx.codes.FORBIDDEN
    assert res.headers["WWW-Authenticate"] == (
        'Bearer realm="PeriodO", error="insufficient_scope", '
        + "error_description="
        + '"The access token does not provide sufficient privileges", '
        + 'error_uri="http://tools.ietf.org/html/rfc6750#section-6.2.3"'
    )


@pytest.mark.client_auth_token("this-token-has-normal-permissions")
def test_authorized_identity_submit_patch(active_user, client, load_json):
    res = client.patch("/d/", json=load_json("test-patch-replace-values-1.json"))
    assert res.status_code == httpx.codes.ACCEPTED
    patch_id = int(res.headers["Location"].split("/")[-2])
    with app.app_context():
        creator = database.query_db_for_one(
            "SELECT created_by FROM patch_request WHERE id = ?", (patch_id,)
        )["created_by"]
        assert creator == active_user.id


@pytest.mark.client_auth_token("this-token-has-normal-permissions")
def test_nonadmin_user_merge_patch(active_user, client, load_json):
    active_user

    # submit the patch
    res = client.patch("/d/", json=load_json("test-patch-replace-values-1.json"))

    # There should be NO link header
    patch_url = urlparse(res.headers["Location"]).path
    res = client.get(patch_url)
    assert "Link" not in res.headers

    # now try to merge the patch
    res = client.post(patch_url + "merge")
    assert res.status_code == httpx.codes.FORBIDDEN
    assert res.headers["WWW-Authenticate"] == (
        'Bearer realm="PeriodO", error="insufficient_scope", '
        + "error_description="
        + '"The access token does not provide sufficient privileges", '
        + 'error_uri="http://tools.ietf.org/html/rfc6750#section-6.2.3"'
    )


@pytest.mark.client_auth_token("this-token-has-admin-permissions")
def test_admin_user_merge_patch(
    admin_user,
    active_user,
    client,
    load_json,
    bearer_auth,
):
    active_user

    # submit the patch as normal user
    res = client.patch(
        "/d/",
        auth=bearer_auth("this-token-has-normal-permissions"),
        json=load_json("test-patch-replace-values-1.json"),
    )

    patch_id = int(res.headers["Location"].split("/")[-2])

    # Admin should see a link header
    patch_url = urlparse(res.headers["Location"]).path
    res = client.get(patch_url)
    assert res.headers.get("Link") == f'<{patch_url + "merge"}>;rel="merge"'

    # now merge the patch
    res = client.post(patch_url + "merge")
    assert res.status_code, httpx.codes.NO_CONTENT
    with app.app_context():
        merger = database.query_db_for_one(
            "SELECT merged_by FROM patch_request WHERE id = ?", (patch_id,)
        )["merged_by"]
        assert merger == admin_user.id


@pytest.mark.client_auth_token("this-token-has-admin-permissions")
def test_noncreator_identity_update_patch(
    admin_user,
    active_user,
    client,
    load_json,
    bearer_auth,
):
    admin_user, active_user

    # submit the patch as normal user
    res = client.patch(
        "/d/",
        auth=bearer_auth("this-token-has-normal-permissions"),
        json=load_json("test-patch-replace-values-1.json"),
    )

    # now try to update the patch as a different user (admin)
    patch_url = urlparse(res.headers["Location"]).path
    res = client.put(
        patch_url + "patch.jsonpatch",
        json=load_json("test-patch-replace-values-2.json"),
    )
    assert res.status_code == httpx.codes.FORBIDDEN
    assert res.headers["WWW-Authenticate"] == (
        'Bearer realm="PeriodO", error="insufficient_scope", '
        + "error_description="
        + '"The access token does not provide sufficient privileges", '
        + 'error_uri="http://tools.ietf.org/html/rfc6750#section-6.2.3"'
    )


@pytest.mark.client_auth_token("this-token-has-normal-permissions")
def test_creator_identity_update_patch(active_user, client, load_json):
    active_user

    # submit the patch
    res = client.patch("/d/", json=load_json("test-patch-replace-values-1.json"))

    # update the patch
    patch_url = urlparse(res.headers["Location"]).path
    res = client.put(
        patch_url + "patch.jsonpatch",
        json=load_json("test-patch-replace-values-2.json"),
    )
    assert res.status_code == httpx.codes.OK


@pytest.mark.client_auth_token("this-token-has-normal-permissions")
def test_creator_identity_update_merged_patch(
    admin_user,
    active_user,
    client,
    load_json,
    bearer_auth,
):
    admin_user, active_user

    # submit the patch
    res = client.patch("/d/", json=load_json("test-patch-replace-values-1.json"))

    # merge the patch (as admin)
    patch_url = urlparse(res.headers["Location"]).path
    res = client.post(
        patch_url + "merge", auth=bearer_auth("this-token-has-admin-permissions")
    )

    # now try to update the patch (as original creator)
    res = client.put(
        patch_url + "patch.jsonpatch",
        json=load_json("test-patch-replace-values-2.json"),
    )
    assert res.status_code == httpx.codes.FORBIDDEN
    assert res.headers["WWW-Authenticate"] == (
        'Bearer realm="PeriodO", error="insufficient_scope", '
        + "error_description="
        + '"The access token does not provide sufficient privileges", '
        + 'error_uri="http://tools.ietf.org/html/rfc6750#section-6.2.3"'
    )
