from collections import OrderedDict
import datetime
from email.utils import parsedate
import json
import sqlite3
from time import mktime
from wsgiref.handlers import format_date_time
from base64 import b64encode
import os
import re
from functools import partial
import random
import string
from urllib.parse import urlencode

import requests

from jsonpatch import JsonPatch, JsonPatchException
from jsonpointer import JsonPointerException

from flask import Flask, abort, g, request, make_response, redirect, session
from flask.ext.restful import (Api, Resource, fields, marshal, marshal_with,
                               reqparse)
from flask.ext.principal import (Principal, Permission, PermissionDenied,
                                 ActionNeed, ItemNeed,
                                 Identity, AnonymousIdentity)

from werkzeug.exceptions import Unauthorized

from secrets import SECRET_KEY, ORCID_CLIENT_ID, ORCID_CLIENT_SECRET

__all__ = ['init_db', 'load_data', 'app']


#########
# Setup #
#########

app = Flask(__name__)
app.config.update(
    DEBUG=True,
    DATABASE='./db.sqlite'
)
app.secret_key = SECRET_KEY

class PeriodOApi(Api):
    def handle_error(self, e):
        response = handle_auth_error(e)
        if response is None:
            return super().handle_error(e)
        else:
            return response

api = PeriodOApi(app)

@app.after_request
def add_cors_headers(response):
    response.headers.add('Access-Control-Allow-Origin', '*')
    response.headers.add('Access-Control-Allow-Headers', 'If-Modified-Since')
    response.headers.add('Access-Control-Expose-Headers', 'Last-Modified')
    return response


##################################
# Authentication & Authorization #
##################################

principals = Principal(app, use_sessions=False)
submit_patch_permission = Permission(ActionNeed('submit-patch'))
accept_patch_permission = Permission(ActionNeed('accept-patch'))

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

@principals.identity_loader
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
            {'WWW-Authenticate': 'Bearer realm="PeriodO", error="insufficient_scope", '
             + 'error_description="The access token does not provide sufficient privileges", '
             + 'error_uri="http://tools.ietf.org/html/rfc6750#section-6.2.3"'})
    return None

def add_user_or_update_credentials(credentials, extra_permissions=()):
    with app.app_context():
        orcid = 'http://orcid.org/{}'.format(credentials['orcid'])
        b64token = b64encode(credentials['access_token'].encode())
        permissions = (ActionNeed('submit-patch'),) + extra_permissions
        db = get_db()
        curs = db.cursor()
        curs.execute(
'''
INSERT OR IGNORE INTO user
(id, name, permissions, b64token, token_expires_at_unixtime, credentials)
VALUES (?, ?, ?, ?, strftime('%s','now') + ?, ?)
''',
            (orcid, credentials['name'], json.dumps(permissions), b64token,
             credentials['expires_in'], json.dumps(credentials)))
        if not curs.lastrowid: # user with this id already in DB
            curs.execute(
'''
UPDATE user SET
name = ?,
b64token = ?,
token_expires_at_unixtime = strftime('%s','now') + ?,
credentials = ?
WHERE id = ?
''',
                (credentials['name'], b64token, credentials['expires_in'],
                 json.dumps(credentials), orcid))
        db.commit()
        return get_identity(b64token)

def get_identity(b64token):
    rows = query_db(
'''
SELECT 
user.id AS user_id, 
user.permissions AS user_permissions, 
patch_request.id AS patch_request_id,
strftime("%s","now") > token_expires_at_unixtime AS token_expired
FROM user LEFT JOIN patch_request
ON user.id = patch_request.created_by AND patch_request.open = 1
WHERE user.b64token = ?
''',
        (b64token,))
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


###############
# API Helpers #
###############

ISO_TIME_FMT = '%Y-%m-%d %H:%M:%S'

class InvalidPatchException(Exception):
    pass

def iso_to_timestamp(iso_timestr, fmt=ISO_TIME_FMT):
    dt = datetime.datetime.strptime(iso_timestr, fmt)
    return mktime(dt.timetuple())

def patch_from_text(patch_text):
    patch_text = patch_text or ''
    if isinstance(patch_text, bytes):
        patch_text = patch_text.decode()
    try:
        patch = json.loads(patch_text)
    except:
        raise InvalidPatchException('Patch data could not be parsed as JSON.')
    patch = JsonPatch(patch)
    return patch

def validate_patch(patch, dataset=None):
    dataset = dataset or query_db('select * from dataset order by created desc', one=True)
    
    # Test to make sure it will apply
    try:
        patch.apply(json.loads(dataset['data']))
    except JsonPatchException:
        raise InvalidPatchException('Not a valid JSON patch.')
    except JsonPointerException:
        raise InvalidPatchException('Could not apply JSON patch to dataset.')

patch_parser = reqparse.RequestParser()

class JsonField(fields.Raw):
    def format(self, value):
        return json.loads(value)


#################
# API Resources #
#################


# HTML representation of root resource is optional and dependent on the
# existence of a folder in static/html containing an index.html file.
HTML_REPR_EXISTS = os.path.exists(os.path.join(
    os.path.dirname(__file__),
    'static',
    'html',
    'index.html'))

if HTML_REPR_EXISTS:

    def output_html(data, code, headers=None):
        if request.path == '/':
            return app.send_static_file('html/index.html')
    api.representations['text/html'] = output_html

    @app.route('/lib/<path:path>')
    @app.route('/dist/<path:path>')
    @app.route('/favicon.ico')
    @app.route('/index.html')
    def static_proxy(path=None):
        return app.send_static_file('html' + request.path)


index_fields = {
    'dataset': fields.Url('dataset', absolute=True),
    'patches': fields.Url('patchlist', absolute=True),
    'register': fields.Url('register', absolute=True),
}

@api.resource('/')
class Index(Resource):
    @marshal_with(index_fields)
    def get(self):
        return {}

dataset_parser = reqparse.RequestParser()
dataset_parser.add_argument('If-Modified-Since', dest='modified', location='headers')
dataset_parser.add_argument('version', type=int, location='args',
                            help='Invalid version number')

@api.resource('/dataset/')
class Dataset(Resource):
    def _get_latest_dataset(self):
        "Returns the latest row in the dataset table."
        return query_db('select * from dataset order by created desc', one=True)
    def get(self):
        args = dataset_parser.parse_args()

        query = 'select * from dataset '
        query_args = ()

        if args['version']:
            query += ' where id = (?) '
            query_args += (args['version'],)
        else:
            query += 'order by created desc'

        dataset = query_db(query, query_args, one=True)

        if not dataset:
            if args['version']:
                return { 'status': 404, 'message': 'Could not find given version.' }, 404
            else:
                return { 'status': 501, 'message': 'No dataset loaded yet.' }, 501

        last_modified = iso_to_timestamp(dataset['created'])
        modified_check = mktime(parsedate(args['modified'])) if args['modified'] else 0

        if modified_check >= last_modified:
            return None, 304

        return json.loads(dataset['data']), 200, {
            'Last-Modified': format_date_time(last_modified),
        }
    @submit_patch_permission.require()
    def patch(self):
        try:
            dataset = self._get_latest_dataset()
            patch = patch_from_text(request.data)
            validate_patch(patch, dataset)
        except InvalidPatchException as e:
            return { 'status': 400, 'message': str(e) }, 400

        db = get_db()
        curs = db.cursor()
        curs.execute(
'''
INSERT INTO patch_request
(created_by, updated_by, created_from, original_patch)
VALUES (?, ?, ?, ?)
''',
            (g.identity.id, g.identity.id, dataset['id'], patch.to_string())
        )
        db.commit()

        return None, 202, {
            'Location': api.url_for(PatchRequest, id=curs.lastrowid)
        }

PATCH_QUERY = """
SELECT *
FROM patch_request
"""

patch_list_fields = OrderedDict((
    ('url', fields.Url('patchrequest', absolute=True)),
    ('created_by', fields.String),
    ('created_at', fields.String),
    ('updated_by', fields.String),
    ('updated_at', fields.String),
    ('created_from', fields.String),
    ('applied_to', fields.String),
    ('text', fields.Url('patch', absolute=True)),
    ('open', fields.Boolean),
    ('merged', fields.Boolean)
))

def make_dataset_url(version):
    return api.url_for(Dataset, _external=True) + '?version=' + str(version)

def is_mergeable(patch_text, dataset=None):
    if dataset is None:
        dataset = query_db('select * from dataset order by created desc', one=True)
    patch = patch_from_text(patch_text)
    mergeable = True
    try:
        patch.apply(json.loads(dataset['data']))
    except (JsonPatchException, JsonPointerException):
        mergeable = False
    return mergeable


def process_patch_row(row):
    d = dict(row)
    d['created_from'] = make_dataset_url(row['created_from'])
    d['applied_to'] = make_dataset_url(row['created_from']) if row['applied_to'] else None
    return d

patch_list_parser = reqparse.RequestParser()
patch_list_parser.add_argument(
    'sort', location='args', type=str, choices=('created_at', 'updated_at'),
    default='updated_at')
patch_list_parser.add_argument(
    'order', location='args', type=str, choices=('asc', 'desc'),
    default='desc')
patch_list_parser.add_argument('open', type=str, choices=('true', 'false'))
patch_list_parser.add_argument('merged', type=str, choices=('true', 'false'))
patch_list_parser.add_argument('limit', type=int, default=25)
patch_list_parser.add_argument('from', type=int, default=0)


@api.resource('/patches/')
class PatchList(Resource):
    def get(self):
        args = patch_list_parser.parse_args()
        query = PATCH_QUERY
        params = ()

        where = []
        if args['open'] is not None:
            where.append('open = ?')
            params += (True if args['open'] == 'true' else False,)
        if args['merged'] is not None:
            where.append('merged = ?')
            params += (True if args['merged'] == 'true' else False,)
        if where:
            query += ' where ' + ' AND '.join(where)

        query += ' order by ' + args['sort'] + ' ' + args['order']

        limit = args['limit']
        if limit < 0: limit = 25
        if limit > 250: limit = 250

        offset = args['from']
        if offset < 0: offset = 0
        query += ' limit ' + str(limit) + ' offset ' + str(offset)

        rows = query_db(query, params)
        data = [process_patch_row(row) for row in rows]
        return marshal(data, patch_list_fields)

patch_fields = patch_list_fields.copy()
patch_fields.update((
    ('mergeable', fields.Boolean),
))

@api.resource('/patches/<int:id>/')
class PatchRequest(Resource):
    def get(self, id):
        row = query_db(PATCH_QUERY + ' where id = ?', (id,), one=True)
        if not row:
            abort(404)
        data = process_patch_row(row)
        data['mergeable'] = is_mergeable(data['text'])
        return marshal(data, patch_fields)

@api.resource('/patches/<int:id>/patch.jsonpatch')
class Patch(Resource):
    def get(self, id):
        row = query_db(PATCH_QUERY + ' where id = ?', (id,), one=True)
        patch = row['applied_patch'] if row['merged'] else row['original_patch']
        return json.loads(patch), 200
    def put(self, id):
        permission = UpdatePatchPermission(id)
        if not permission.can(): raise PermissionDenied(permission)
        try:
            patch = patch_from_text(request.data)
            validate_patch(patch)
        except InvalidPatchException as e:
            if str(e) != 'Could not apply JSON patch to dataset.':
                return { 'status': 400, 'message': str(e) }, 400

        db = get_db()
        curs = db.cursor()
        curs.execute(
'''
UPDATE patch_request SET
original_patch = ?,
updated_by = ?
WHERE id = ?
''',
            (patch.to_string(), g.identity.id, id)
        )
        db.commit()

@api.resource('/patches/<int:id>/merge')
class PatchMerge(Resource):
    @accept_patch_permission.require()
    def post(self, id):
        row = query_db(PATCH_QUERY + ' where id = ?', (id,), one=True)

        if not row:
            abort(404)
        if row['merged']:
            return { 'message': 'Patch is already merged.' }, 404
        if not row['open']:
            return { 'message': 'Closed patches cannot be merged.' }, 404

        dataset = query_db('select * from dataset order by created desc', one=True)
        mergeable = is_mergeable(row['original_patch'], dataset)

        if not mergeable:
            return { 'message': 'Patch is not mergeable.' }, 400

        patch = patch_from_text(row['original_patch'])

        # Should this be ordered?
        new_data = patch.apply(json.loads(dataset['data']))

        db = get_db()
        curs = db.cursor()
        curs.execute('insert into dataset (data) values (?);', (json.dumps(new_data),))
        curs.execute(
            '''
            update patch_request
            set merged = 1,
                open = 0,
                merged_at = CURRENT_TIMESTAMP,
                merged_by = ?,
                applied_to = ?,
                resulted_in = ?
            where id = ?;
            ''',
            (g.identity.id, dataset['id'], curs.lastrowid, row['id'])
        )
        db.commit()

        return None, 204

def generate_state_token():
    return ''.join(random.choice(string.ascii_uppercase + string.digits)
                   for x in range(32))

@api.resource('/register')
class Register(Resource):
    def get(self):
        state_token = generate_state_token()
        session['state_token'] = state_token
        params = {
            'client_id': ORCID_CLIENT_ID,
            'redirect_uri': api.url_for(Registered, _external=True),
            'response_type': 'code',
            'scope': '/authenticate',
            'state': state_token,
        }
        return redirect(
            'https://orcid.org/oauth/authorize?{}'.format(urlencode(params)))

@api.resource('/registered')
class Registered(Resource):
    def get(self):
        if not request.args['state'] == session.pop('state_token'):
            abort(403)
        data = {
            'client_id': ORCID_CLIENT_ID,
            'client_secret': ORCID_CLIENT_SECRET,
            'code': request.args['code'],
            'grant_type': 'authorization_code',
            'redirect_uri': api.url_for(Registered, _external=True),
            'scope': '/authenticate',
        }
        response = requests.post(
            'https://pub.orcid.org/oauth/token',
            headers={'Accept': 'application/json'},
            allow_redirects=True, data=data)
        credentials = response.json()
        print(credentials)
        identity = add_user_or_update_credentials(credentials)
        return { 'access_token': identity.b64token.decode() }

######################
#  Database handling #
######################

def init_db():
    with app.app_context():
        db = get_db()
        with app.open_resource('schema.sql', mode='r') as schema_file:
            db.cursor().executescript(schema_file.read())
        db.commit()

def load_data(datafile):
    with app.app_context():
        db = get_db()
        with open(datafile) as f:
            data = json.load(f)
            db.execute(u'insert into dataset (data) values (?)',
                       (json.dumps(data),))
        db.commit()
        
def get_db():
    db = getattr(g, '_database', None)
    if db is None:
        db = g._database = sqlite3.connect(app.config['DATABASE'])
        db.row_factory = sqlite3.Row
    return db

def query_db(query, args=(), one=False):
    curs = get_db().execute(query, args)
    rows = curs.fetchall()
    curs.close()
    return (rows[0] if rows else None) if one else rows

@app.teardown_appcontext
def close_connection(exception):
    db = getattr(g, '_database', None)
    if db is not None:
        db.close()


############################
# End of meaningful things #
############################

if __name__ == '__main__':
    app.run()
