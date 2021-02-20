import httpx
import pytest
from periodo import app, database


def test_active_identity(active_identity):
    assert active_identity.id is not None
    assert active_identity.auth_type == 'bearer'
    with app.app_context():
        row = database.query_db(
            'SELECT name, permissions, b64token FROM user WHERE id = ?',
            (active_identity.id,),
            one=True
        )
        assert row['name'] == active_identity.name
        assert row['b64token'] == active_identity.b64token
        assert row['permissions'] == (
            '[["action", "submit-patch"], ["action", "create-bag"]]'
        )


def test_expired_identity(expired_identity):
    assert expired_identity.id is None
    assert expired_identity.auth_type is None


def test_no_auth(client):
    res = client.patch('/d/')
    assert res.status_code == httpx.codes.UNAUTHORIZED
    assert res.headers['WWW-Authenticate'] == 'Bearer realm="PeriodO"'


def test_unsupported_auth_method(client):
    res = client.patch(
        '/d/',
        headers={'Authorization': 'Basic QWxhZGRpbjpvcGVuIHNlc2FtZQ=='}
    )
    assert res.status_code == httpx.codes.UNAUTHORIZED
    assert res.headers['WWW-Authenticate'] == 'Bearer realm="PeriodO"'


def test_malformed_bearer_token(client):
    res = client.patch('/d/', headers={'Authorization': 'Bearer =!@#$%^&*()_+'})
    assert res.status_code == httpx.codes.UNAUTHORIZED
    assert res.headers['WWW-Authenticate'] == (
        'Bearer realm="PeriodO", error="invalid_token", '
        + 'error_description="The access token is malformed", '
        + 'error_uri="http://tools.ietf.org/html/rfc6750#section-6.2.2"'
    )


@pytest.mark.client_auth_token('this-token-is-not-in-the-database')
def test_token_not_in_database(client):
    res = client.patch('/d/')
    assert res.status_code == httpx.codes.UNAUTHORIZED
    assert res.headers['WWW-Authenticate'] == (
        'Bearer realm="PeriodO", error="invalid_token", '
        + 'error_description="The access token is invalid", '
        + 'error_uri="http://tools.ietf.org/html/rfc6750#section-6.2.2"'
    )


@pytest.mark.client_auth_token('this-is-an-expired-token')
def test_expired_token(expired_identity, client):
    res = client.patch('/d/')
    assert res.status_code == httpx.codes.UNAUTHORIZED
    assert res.headers['WWW-Authenticate'] == (
        'Bearer realm="PeriodO", error="invalid_token", '
        + 'error_description="The access token expired", '
        + 'error_uri="http://tools.ietf.org/html/rfc6750#section-6.2.2"'
    )
