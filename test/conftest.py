import httpx
import json
import os
import pytest
import tempfile
from base64 import b64encode
from urllib.parse import urlparse
from flask_principal import ActionNeed
from periodo import app, commands, auth, DEV_SERVER_NAME


class BearerAuth(httpx.Auth):
    def __init__(self, token):
        self.encoded_token = b64encode(token.encode()).decode()

    def auth_flow(self, request):
        request.headers['Authorization'] = f'Bearer {self.encoded_token}'
        yield request


@pytest.fixture
def load_json(shared_datadir):
    def _load_json(filename):
        return json.loads((shared_datadir / filename).read_text())
    return _load_json


@pytest.fixture
def init_db(shared_datadir):
    app.config['TESTING'] = True
    db_fd, app.config['DATABASE'] = tempfile.mkstemp()
    commands.init_db()
    commands.load_data(shared_datadir / 'test-data.json')
    yield
    # teardown
    os.close(db_fd)
    os.unlink(app.config['DATABASE'])


@pytest.fixture
def active_user(init_db):
    init_db
    with app.app_context():
        return auth.add_user_or_update_credentials({
            'name': 'Testy Testerson',
            'access_token': 'this-token-has-normal-permissions',
            'expires_in': 631138518,
            'orcid': '1234-5678-9101-112X',
        })


@pytest.fixture
def expired_user(init_db):
    init_db
    with app.app_context():
        return auth.add_user_or_update_credentials({
            'name': 'Eric Expired',
            'access_token': 'this-is-an-expired-token',
            'expires_in': -3600,
            'orcid': '1211-1098-7654-321X',
        })


@pytest.fixture
def unauthorized_user(init_db):
    init_db
    with app.app_context():
        return auth.add_user_or_update_credentials({
            'name': 'Dangerous Dan',
            'access_token': 'this-token-has-no-permissions',
            'expires_in': 631138518,
            'orcid': '0000-0000-0000-000X',
            'permissions': (),
        })


@pytest.fixture
def admin_user(init_db):
    init_db
    with app.app_context():
        return auth.add_user_or_update_credentials({
            'name': 'Super Admin',
            'access_token': 'this-token-has-admin-permissions',
            'expires_in': 3600,
            'orcid': '1211-1098-7654-321X',
            'permissions': auth.DEFAULT_PERMISSIONS + (
                ActionNeed('accept-patch'),
                ActionNeed('create-graph'),
            )
        })


@pytest.fixture
def bearer_auth():
    def _bearer_auth(token):
        return BearerAuth(token)
    return _bearer_auth


@pytest.fixture
def client(request, init_db):
    init_db
    marker = request.node.get_closest_marker('client_auth_token')
    if marker is None:
        auth = None
    else:
        auth = BearerAuth(marker.args[0])
    with httpx.Client(
            app=app,
            base_url=f'http://{DEV_SERVER_NAME}',
            auth=auth
    ) as client:
        yield client


@pytest.fixture
def submit_and_merge_patch(
        active_user,
        admin_user,
        client,
        bearer_auth,
        load_json
):
    active_user, admin_user

    def _submit_and_merge_patch(filename):
        res = client.patch(
            '/d/',
            json=load_json(filename),
            auth=bearer_auth('this-token-has-normal-permissions')
        )
        patch_url = urlparse(res.headers['Location']).path
        return client.post(
            patch_url + 'merge',
            auth=bearer_auth('this-token-has-admin-permissions')
        )

    return _submit_and_merge_patch
