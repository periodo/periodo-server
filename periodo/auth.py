import re
import json
from base64 import b64encode
from functools import partial
from flask import request, make_response
from flask_principal import (Permission, PermissionDenied,
                             ActionNeed, ItemNeed,
                             Identity, AnonymousIdentity)
from periodo import database
from werkzeug.exceptions import Unauthorized

submit_patch_permission = Permission(ActionNeed('submit-patch'))
accept_patch_permission = Permission(ActionNeed('accept-patch'))
update_bag_permission = Permission(ActionNeed('create-bag'))
update_graph_permission = Permission(ActionNeed('create-graph'))

ERROR_URIS = {
    'invalid_request': 'http://tools.ietf.org/html/rfc6750#section-6.2.1',
    'invalid_token': 'http://tools.ietf.org/html/rfc6750#section-6.2.2',
    'insufficient_scope': 'http://tools.ietf.org/html/rfc6750#section-6.2.3',
}


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

    def can(self, permission):
        raise self.exception


UpdatePatchNeed = partial(ItemNeed, type='patch_request', method='update')


class UpdatePatchPermission(Permission):
    def __init__(self, patch_request_id):
        super().__init__(UpdatePatchNeed(value=patch_request_id))


def load_identity_from_authorization_header():
    auth = request.headers.get('Authorization', None)
    if auth is None or not auth.startswith('Bearer '):
        return UnauthenticatedIdentity()
    match = re.match(r'Bearer ([\w\-\.~\+/]+=*)$', auth, re.ASCII)
    if not match:
        return UnauthenticatedIdentity(
            'invalid_token', 'The access token is malformed')
    return get_identity(match.group(1).encode())


def handle_auth_error(e):
    if isinstance(e, AuthenticationFailed):
        parts = ['Bearer realm="PeriodO"']
        if e.error:
            parts.append('error="{}"'.format(e.error))
        if e.error_description:
            parts.append('error_description="{}"'.format(e.error_description))
        if e.error_uri:
            parts.append('error_uri="{}"'.format(e.error_uri))
        return make_response(e.error_description or '', 401,
                             {'WWW-Authenticate': ', '.join(parts)})
    if isinstance(e, PermissionDenied):
        description = 'The access token does not provide sufficient privileges'
        return make_response(
            description, 403,
            {'WWW-Authenticate':
             'Bearer realm="PeriodO", error="insufficient_scope", '
             + 'error_description='
             + '"The access token does not provide sufficient privileges", '
             + 'error_uri="http://tools.ietf.org/html/rfc6750#section-6.2.3"'})
    return None


def add_user_or_update_credentials(credentials, extra_permissions=()):
    orcid = 'https://orcid.org/{}'.format(credentials['orcid'])
    b64token = b64encode(credentials['access_token'].encode())
    permissions = (
        (ActionNeed('submit-patch'),
         ActionNeed('create-bag'))
        + extra_permissions
    )
    db = database.get_db()
    cursor = db.cursor()
    cursor.execute('''
    INSERT OR IGNORE INTO user (
    id,
    name,
    permissions,
    b64token,
    token_expires_at,
    credentials)
    VALUES (?, ?, ?, ?, strftime('%s','now') + ?, ?) ''',
                   (orcid,
                    credentials['name'],
                    json.dumps(permissions),
                    b64token,
                    credentials['expires_in'],
                    json.dumps(credentials)))
    if not cursor.lastrowid:  # user with this id already in DB
        cursor.execute('''
        UPDATE user SET
        name = ?,
        b64token = ?,
        token_expires_at = strftime('%s','now') + ?,
        credentials = ?
        WHERE id = ?''',
                       (credentials['name'],
                        b64token,
                        credentials['expires_in'],
                        json.dumps(credentials),
                        orcid))

    return get_identity(b64token, cursor)


def get_identity(b64token, cursor=None):
    if cursor is None:
        cursor = database.get_db().cursor()
    rows = cursor.execute('''
    SELECT
    user.id AS user_id,
    user.permissions AS user_permissions,
    patch_request.id AS patch_request_id,
    strftime("%s","now") > token_expires_at AS token_expired
    FROM user LEFT JOIN patch_request
    ON user.id = patch_request.created_by AND patch_request.open = 1
    WHERE user.b64token = ?''', (b64token,)).fetchall()
    if not rows:
        return UnauthenticatedIdentity(
            'invalid_token', 'The access token is invalid')
    if rows[0]['token_expired']:
        return UnauthenticatedIdentity(
            'invalid_token', 'The access token expired')
    identity = Identity(rows[0]['user_id'], auth_type='bearer')
    identity.b64token = b64token
    for p in json.loads(rows[0]['user_permissions']):
        identity.provides.add(tuple(p))
    for r in rows:
        if r['patch_request_id'] is not None:
            identity.provides.add(UpdatePatchNeed(value=r['patch_request_id']))
    return identity
