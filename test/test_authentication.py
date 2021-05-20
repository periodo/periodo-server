import httpx
import pytest
from periodo import app, database


def test_active_user(active_user):
    assert active_user.name == 'Testy Testerson'
    with app.app_context():
        row = database.query_db_for_one(
            '''SELECT
            name,
            b64token,
            permissions,
            strftime("%s","now") > token_expires_at AS token_expired
            FROM user WHERE id = ?''',
            (active_user.id,)
        )
        assert row['name'] == active_user.name
        assert row['b64token'] == active_user.b64token
        assert not row['token_expired']
        assert row['permissions'] == (
            '[["action", "submit-patch"], ["action", "create-bag"]]'
        )


def test_expired_user(expired_user):
    assert expired_user.name == 'Eric Expired'
    with app.app_context():
        row = database.query_db_for_one(
            '''SELECT
            name,
            b64token,
            strftime("%s","now") > token_expires_at AS token_expired
            FROM user WHERE id = ?''',
            (expired_user.id,)
        )
        assert row['name'] == expired_user.name
        assert row['b64token'] == expired_user.b64token
        assert row['token_expired']


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
def test_expired_token(expired_user, client):
    expired_user
    res = client.patch('/d/')
    assert res.status_code == httpx.codes.UNAUTHORIZED
    assert res.headers['WWW-Authenticate'] == (
        'Bearer realm="PeriodO", error="invalid_token", '
        + 'error_description="The access token expired", '
        + 'error_uri="http://tools.ietf.org/html/rfc6750#section-6.2.2"'
    )
