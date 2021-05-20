import re
import json
from base64 import b64encode
from collections import namedtuple
from functools import partial
from flask import request, make_response
from flask_principal import (Permission, PermissionDenied,
                             ActionNeed, ItemNeed,
                             Identity, AnonymousIdentity)
from periodo import database, app
from werkzeug.exceptions import Unauthorized

submit_patch_permission = Permission(ActionNeed('submit-patch'))
accept_patch_permission = Permission(ActionNeed('accept-patch'))
update_bag_permission = Permission(ActionNeed('create-bag'))
update_graph_permission = Permission(ActionNeed('create-graph'))

action_need_descriptions = {
    'submit-patch': 'can submit proposed changes to the dataset',
    'accept-patch': 'can accept and merge changes to the dataset',
    'create-bag': 'can create and update bags of periods',
    'create-graph': 'can create and update graphs of related triples',
}

DEFAULT_PERMISSIONS = (
    ActionNeed('submit-patch'),
    ActionNeed('create-bag'),
)

ERROR_URIS: dict = {
    'invalid_request': 'http://tools.ietf.org/html/rfc6750#section-6.2.1',
    'invalid_token': 'http://tools.ietf.org/html/rfc6750#section-6.2.2',
    'insufficient_scope': 'http://tools.ietf.org/html/rfc6750#section-6.2.3',
}


class User:
    def __init__(self, user_id, name, b64token):
        self.id = user_id
        self.name = name
        self.b64token = b64token


class AuthenticationFailed(Unauthorized):
    def __init__(self, error=None, description=None):
        self.error = error
        self.error_description = description
        self.error_uri = ERROR_URIS.get(error, None)
        super().__init__()


class UnauthenticatedIdentity(AnonymousIdentity):
    def __init__(self, *args, **kwargs):
        self.exception = AuthenticationFailed(*args, **kwargs)
        super().__init__()

    def can(self, _):
        raise self.exception


UpdatePatchNeed = partial(ItemNeed, type='patch_request', method='update')


class UpdatePatchPermission(Permission):
    def __init__(self, patch_request_id):
        super().__init__(UpdatePatchNeed(value=patch_request_id))


Credentials = namedtuple('Credentials', [
    'orcid',
    'name',
    'access_token',
    'expires_in',
    'token_type',
    'scope',
    'refresh_token',
    'permissions',
], defaults=[
    'bearer',
    '/authenticate',
    None,
    DEFAULT_PERMISSIONS,
])


def _create_credentials(d):
    if 'orcid' in d and len(d.get('name', '')) == 0:
        # User has made their name private, so just use their ORCID as name
        d['name'] = d['orcid']
    return Credentials(**{
        field: d[field] for field in Credentials._fields if field in d
    })


def _serialize_credentials(credentials):
    if not type(credentials) == Credentials:
        raise TypeError
    return json.dumps({
        k: v for k, v in credentials._asdict().items() if not k == 'permissions'
    }, ensure_ascii=False)


def describe(needs):
    description = set()
    for need in needs:
        classname = type(need).__name__
        if classname == 'tuple' and len(need) == 2:
            method, value = need
            if method == 'action':
                description.add(action_need_descriptions[value])
        elif classname == 'ItemNeed':
            if need.method == 'update' and need.type == 'patch_request':
                description.add('can update submissions of proposed changes')
    return list(description)


def load_identity_from_authorization_header():
    auth = request.headers.get('Authorization', None)
    if auth is None or not auth.startswith('Bearer '):
        return UnauthenticatedIdentity()
    match = re.match(r'Bearer ([\w\-\.~\+/]+=*)$', auth, re.ASCII)
    if not match:
        app.logger.debug(
            'failed to load bearer token from authorization header')
        return UnauthenticatedIdentity(
            'invalid_token', 'The access token is malformed')
    return _get_identity(match.group(1).encode())


def handle_auth_error(e):
    if isinstance(e, AuthenticationFailed):
        parts = ['Bearer realm="PeriodO"']
        if e.error:
            parts.append('error="{}"'.format(e.error))
        if e.error_description:
            parts.append('error_description="{}"'.format(e.error_description))
        if e.error_uri:
            parts.append('error_uri="{}"'.format(e.error_uri))
        app.logger.debug(
            'authentication failed: ' + (', '.join(parts)))
        return make_response(e.error_description or '', 401,
                             {'WWW-Authenticate': ', '.join(parts)})
    if isinstance(e, PermissionDenied):
        description = 'The access token does not provide sufficient privileges'
        app.logger.debug(description)
        return make_response(
            description, 403,
            {'WWW-Authenticate':
             'Bearer realm="PeriodO", error="insufficient_scope", '
             + 'error_description='
             + '"The access token does not provide sufficient privileges", '
             + 'error_uri="http://tools.ietf.org/html/rfc6750#section-6.2.3"'})
    return None


def add_user_or_update_credentials(credential_data):
    credentials = _create_credentials(credential_data)

    orcid = f'https://orcid.org/{credentials.orcid}'
    b64token = b64encode(credentials.access_token.encode())
    serialized_credentials = _serialize_credentials(credentials)

    with database.open_cursor(write=True) as cursor:
        cursor.execute('''
        INSERT OR IGNORE INTO user (
          id,
          name,
          permissions,
          b64token,
          token_expires_at,
          credentials
        )
        VALUES (?, ?, ?, ?, strftime('%s','now') + ?, ?)
        ''', (
            orcid,
            credentials.name,
            json.dumps(credentials.permissions),
            b64token,
            credentials.expires_in,
            serialized_credentials,
        ))
        if not cursor.lastrowid:  # user with this id already in DB
            cursor.execute('''
            UPDATE user SET
            name = ?,
            b64token = ?,
            token_expires_at = strftime('%s','now') + ?,
            credentials = ?
            WHERE id = ?
            ''', (
                credentials.name,
                b64token,
                credentials.expires_in,
                serialized_credentials,
                orcid
            ))

    return User(orcid, credentials.name, b64token)


def _get_identity(b64token):
    rows = database.query_db_for_all('''
    SELECT
    user.id AS user_id,
    user.permissions AS user_permissions,
    patch_request.id AS patch_request_id,
    strftime("%s","now") > token_expires_at AS token_expired
    FROM user LEFT JOIN patch_request
    ON user.id = patch_request.created_by AND patch_request.open = 1
    WHERE user.b64token = ?
    ''', (b64token,))
    if not rows:
        return UnauthenticatedIdentity(
            'invalid_token', 'The access token is invalid')
    if rows[0]['token_expired']:
        return UnauthenticatedIdentity(
            'invalid_token', 'The access token expired')
    identity = Identity(rows[0]['user_id'], auth_type='bearer')
    for p in json.loads(rows[0]['user_permissions']):
        identity.provides.add(tuple(p))
    for r in rows:
        if r['patch_request_id'] is not None:
            identity.provides.add(UpdatePatchNeed(value=r['patch_request_id']))
    return identity
