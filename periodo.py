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
from functools import partial, reduce
import random
import string
from urllib.parse import urlencode

import requests

from rdflib import Graph, URIRef, Literal, BNode
from rdflib.collection import Collection
from rdflib.namespace import Namespace, RDF, DCTERMS, XSD, VOID, FOAF
PROV = Namespace('http://www.w3.org/ns/prov#')

from jsonpatch import JsonPatch, JsonPatchException
from jsonpointer import JsonPointerException

from flask import (Flask, abort, g, request, make_response, redirect,
                   session, url_for)
from flask.ext.restful import (Api, Resource, fields, marshal, marshal_with,
                               reqparse)
from flask.ext.principal import (Principal, Permission, PermissionDenied,
                                 ActionNeed, ItemNeed,
                                 Identity, AnonymousIdentity)

from werkzeug.exceptions import Unauthorized

from identifier import (replace_skolem_ids, prefix,
                        COLLECTION_SEQUENCE_LENGTH,
                        DEFINITION_SEQUENCE_LENGTH,
                        IDENTIFIER_RE)
import provenance
from secrets import SECRET_KEY, ORCID_CLIENT_ID, ORCID_CLIENT_SECRET

__all__ = ['init_db', 'load_data', 'app']


#########
# Setup #
#########

PERIODO = Namespace('http://n2t.net/ark:/99152/')

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
    def make_response(self, data, *args, **kwargs):
        # Override content negotation for content-type-specific URLs.
        if request.path.endswith('.json'):
            res = self.representations['application/json'](data, *args, **kwargs)
            res.content_type = 'application/json'
            return res
        if request.path.endswith('.jsonld'):
            res = self.representations['application/json'](data, *args, **kwargs)
            res.content_type = 'application/ld+json'
            return res
        return super().make_response(data, *args, **kwargs)

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

CHANGE_PATH_PATTERN = re.compile(r'''
/periodCollections/
({id_pattern})   # match collection ID
(?:
  /definitions/
  ({id_pattern}) # optionally match definition ID
)?
'''.format(id_pattern=IDENTIFIER_RE.pattern[1:-1]), re.VERBOSE)


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
    dataset = dataset or get_dataset()

    # Test to make sure it will apply
    try:
        patch.apply(json.loads(dataset['data']))
    except JsonPatchException:
        raise InvalidPatchException('Not a valid JSON patch.')
    except JsonPointerException:
        raise InvalidPatchException('Could not apply JSON patch to dataset.')

    matches = [CHANGE_PATH_PATTERN.match(change['path']) for change in patch]
    affected_entities = reduce(
        lambda s, groups: s | set(groups),
        [m.groups() for m in matches if m is not None], set())
    affected_entities.discard(None)
    return affected_entities

patch_parser = reqparse.RequestParser()

class JsonField(fields.Raw):
    def format(self, value):
        return json.loads(value)

def describe_dataset(cursor, data, created):
    contributors = query_db(
'''
SELECT DISTINCT created_by, updated_by
FROM patch_request
WHERE merged = 1
AND id > 1  -- ignore initial load
''', cursor=cursor)
    with open(os.path.join(os.path.dirname(__file__), 'void-stub.ttl')) as f:
        description = Graph().parse(file=f, format='turtle')
    ns = Namespace(description.value(
        predicate=RDF.type, object=VOID.DatasetDescription))
    dataset_g = Graph().parse(data=json.dumps(data), format='json-ld')

    for part in description[ ns.d : VOID.classPartition ]:
        clazz = description.value(subject=part, predicate=VOID['class'])
        entity_count = len(dataset_g.query(
'''
SELECT DISTINCT ?s
WHERE {
?s a <%s> .
FILTER (STRSTARTS(STR(?s), "%s"))
}
''' % (clazz, ns)))
        description.add(
            (part, VOID.entities, Literal(entity_count, datatype=XSD.integer)))

    def add_to_description(p, o):
        description.add((ns.d, p, o))
    add_to_description(
         DCTERMS.modified, Literal(created, datatype=XSD.dateTime))
    add_to_description(
         VOID.triples, Literal(len(dataset_g), datatype=XSD.integer))
    for row in contributors:
        add_to_description(
             DCTERMS.contributor, URIRef(row['created_by']))
        if row['updated_by']:
            add_to_description(
                 DCTERMS.contributor, URIRef(row['updated_by']))
    return description.serialize(format='turtle')


def get_dataset(version=None, cursor=None):
    if version is None:
        return query_db(
            'SELECT * FROM dataset ORDER BY id DESC',
            one=True, cursor=cursor)
    else:
        return query_db(
            'SELECT * FROM dataset WHERE dataset.id = ?', (version,),
            one=True, cursor=cursor)

def add_new_version_of_dataset(cursor, data):
    now = query_db("SELECT CURRENT_TIMESTAMP AS now", one=True, cursor=cursor)['now']
    cursor.execute(
        'INSERT into DATASET (data, description, created) VALUES (?,?,?)',
        (json.dumps(data), describe_dataset(cursor, data, now), now))

def attach_to_dataset(o):
    o['primaryTopicOf'] = { 'id': prefix(request.path[1:]),
                            'inDataset': prefix('d') }
    return o


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
    @app.route('/lib/<path:path>')
    @app.route('/dist/<path:path>')
    @app.route('/favicon.ico')
    @app.route('/index.html')
    def static_proxy(path=None):
        return app.send_static_file('html' + request.path)

@api.representation('text/html')
def output_html(data, code, headers=None):
    if HTML_REPR_EXISTS and request.path == '/':
        res = app.send_static_file('html/index.html')
    else:
        res = make_response('This resource is not available as text/html', 406)
        res.headers.add('Link', '<>; rel="alternate"; type="application/json"')
    if request.path == '/':
        res.headers.add('Link', '</>; rel="alternate"; type="text/turtle"; title="VoID description of the PeriodO Period Gazetteer')
    res.headers.extend(headers or {})
    return res

@api.representation('text/turtle')
def output_turtle(data, code, headers=None):
    if request.path == '/':
        res = void()
    else:
        res = make_response('This resource is not available as text/turtle', 406)
        res.headers.add('Link', '<>; rel="alternate"; type="application/json"')
    res.headers.extend(headers or {})
    return res

@api.representation('application/ld+json')
def output_jsonld(data, code, headers=None):
    res = make_response(json.dumps(data), code, headers)
    res.headers.extend(headers or {})
    return res

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


@app.route('/h')
def history():
    '''Respond with JSON-LD representation of change history'''
    history_g = Graph()
    changelog = Collection(history_g, URIRef('#changelog'))
    for row in query_db('''
SELECT
  id,
  created_at,
  created_by,
  updated_by,
  merged_at,
  merged_by,
  applied_to,
  resulted_in,
  affected_entities
FROM patch_request
WHERE merged = 1
ORDER BY id ASC
'''):
        change = URIRef('#change-{}'.format(row['id']))
        patch = URIRef('#patch-{}'.format(row['id']))
        history_g.add((patch,
                       FOAF.page,
                       PERIODO[prefix(url_for('patch', id=row['id']))]))
        history_g.add((change,
                       PROV.startedAtTime,
                       Literal(row['created_at'], datatype=XSD.dateTime)))
        history_g.add((change,
                       PROV.endedAtTime,
                       Literal(row['merged_at'], datatype=XSD.dateTime)))
        dataset = PERIODO[prefix(url_for('abstract_dataset'))]
        version_in = PERIODO[prefix(
            url_for('abstract_dataset', version=row['applied_to']))]
        history_g.add((version_in, PROV.specializationOf, dataset))
        version_out = PERIODO[prefix(
            url_for('abstract_dataset', version=row['resulted_in']))]
        history_g.add((version_out, PROV.specializationOf, dataset))

        history_g.add((change, PROV.used, version_in))
        history_g.add((change, PROV.used, patch))
        history_g.add((change, PROV.generated, version_out))

        for entity_id in json.loads(row['affected_entities']):
            entity = PERIODO[entity_id]
            entity_version = PERIODO[
                entity_id + '?version={}'.format(row['resulted_in'])]
            prev_entity_version = PERIODO[
                entity_id + '?version={}'.format(row['applied_to'])]
            history_g.add(
                (entity_version, PROV.specializationOf, entity))
            history_g.add(
                (entity_version, PROV.wasRevisionOf, prev_entity_version))
            history_g.add((change, PROV.generated, entity_version))

        for field, term in (('created_by', 'submitted'),
                            ('updated_by', 'updated'),
                            ('merged_by', 'merged')):
            if row[field] == 'initial-data-loader':
                continue
            agent = URIRef(row[field])
            association = URIRef('#patch-{}-{}'.format(row['id'], term))
            history_g.add((change, PROV.wasAssociatedWith, agent))
            history_g.add((change, PROV.qualifiedAssociation, association))
            history_g.add((association, PROV.agent, agent))
            history_g.add((association,
                           PROV.hadRole,
                           PERIODO[prefix(url_for('vocab') + '#' + term)]))

        changelog.append(change)

    out = history_g.serialize(
        format='json-ld', context=provenance.CONTEXT).decode('utf-8')
    return make_response(
        out, 200,
        {'Content-Type': 'application/ld+json'})


@app.route('/v')
def vocab():
    return app.send_static_file('vocab.ttl')

# http://www.w3.org/TR/void/#well-known
@app.route('/.well-known/void')
def void():
    return make_response(get_dataset()['description'], 200, {
        'Content-Type': 'text/turtle',
        'Link': '</>; rel="alternate"; type="text/html"',
    })


# URIs for abstract resources (no representations, just 303 See Other)


@app.route('/d', endpoint='abstract_dataset')
def see_dataset():
    return redirect(url_for('dataset', **request.args), code=303)


@app.route('/<string(length=%s):collection_id>'
           % (COLLECTION_SEQUENCE_LENGTH + 1))
def see_collection(collection_id):
    if request.accept_mimetypes.best == 'application/json':
        url = url_for('collection-json', collection_id=collection_id,
                      **request.args)
    elif request.accept_mimetypes.best == 'application/ld+json':
        url = url_for('collection-jsonld', collection_id=collection_id,
                      **request.args)
    else:
        url = url_for('index', _anchor=request.path[1:])
    return redirect(url, code=303)


@app.route('/<string(length=%s):definition_id>'
           % (COLLECTION_SEQUENCE_LENGTH + 1 + DEFINITION_SEQUENCE_LENGTH + 1))
def see_definition(definition_id):
    if request.accept_mimetypes.best == 'application/json':
        url = url_for('definition-json', definition_id=definition_id,
                      **request.args)
    elif request.accept_mimetypes.best == 'application/ld+json':
        url = url_for('definition-jsonld', definition_id=definition_id,
                      **request.args)
    else:
        url = url_for('index', _anchor=request.path[1:])
    return redirect(url, code=303)


dataset_parser = reqparse.RequestParser()
dataset_parser.add_argument('If-Modified-Since', dest='modified', location='headers')
dataset_parser.add_argument('version', type=int, location='args',
                            help='Invalid version number')

@api.resource('/d/', '/d.json', '/d.jsonld')
class Dataset(Resource):
    def get(self):
        args = dataset_parser.parse_args()

        query = 'select * from dataset '
        query_args = ()

        if args['version']:
            query += ' where id = (?) '
            query_args += (args['version'],)
        else:
            query += 'ORDER BY id DESC'

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

        return attach_to_dataset(json.loads(dataset['data'])), 200, {
            'Last-Modified': format_date_time(last_modified)}

    @submit_patch_permission.require()
    def patch(self):
        try:
            patch_request_id = create_patch_request(
                patch_from_text(request.data), g.identity.id)
            return None, 202, {
                'Location': api.url_for(PatchRequest, id=patch_request_id)
            }
        except InvalidPatchException as e:
            return {'status': 400, 'message': str(e)}, 400


def create_patch_request(patch, user_id):
    dataset = get_dataset()
    affected_entities = validate_patch(patch, dataset)
    db = get_db()
    curs = db.cursor()
    curs.execute('''
INSERT INTO patch_request
(created_by, updated_by, created_from, affected_entities, original_patch)
VALUES (?, ?, ?, ?, ?)
    ''', (user_id, user_id, dataset['id'],
          json.dumps(sorted(affected_entities)), patch.to_string()))
    db.commit()
    return curs.lastrowid


def find_version_of_last_update(entity_id, version):
    for row in query_db('''
    SELECT affected_entities, resulted_in
    FROM patch_request
    WHERE merged = 1
    AND resulted_in <= ?
    ORDER BY id DESC''', (version,)):
        if prefix(entity_id) in json.loads(row['affected_entities']):
            return row['resulted_in']
    return None


def redirect_to_last_update(entity_id, version):
    if version is None:
        return None
    v = find_version_of_last_update(entity_id, version)
    if v is None:
        abort(404)
    if v == int(version):
        return None
    return redirect(request.path + '?version={}'.format(v), code=301)


@api.resource('/<string(length=%s):collection_id>.json'
              % (COLLECTION_SEQUENCE_LENGTH + 1),
              endpoint='collection-json')
@api.resource('/<string(length=%s):collection_id>.jsonld'
              % (COLLECTION_SEQUENCE_LENGTH + 1),
              endpoint='collection-jsonld')
class PeriodCollection(Resource):
    def get(self, collection_id):
        version = request.args.get('version')
        new_location = redirect_to_last_update(collection_id, version)
        if new_location is not None:
            return new_location
        dataset = get_dataset(version=version)
        o = json.loads(dataset['data'])
        if not 'periodCollections' in o:
            abort(404)
        collection_key = prefix(collection_id)
        if not collection_key in o['periodCollections']:
            abort(404)
        collection = o['periodCollections'][collection_key]
        collection['@context'] = o['@context']
        return attach_to_dataset(collection)

@api.resource('/<string(length=%s):definition_id>.json'
              % (COLLECTION_SEQUENCE_LENGTH + 1 +
                 DEFINITION_SEQUENCE_LENGTH + 1),
              endpoint='definition-json')
@api.resource('/<string(length=%s):definition_id>.jsonld'
              % (COLLECTION_SEQUENCE_LENGTH + 1 +
                 DEFINITION_SEQUENCE_LENGTH + 1),
              endpoint='definition-jsonld')
class PeriodDefinition(Resource):
    def get(self, definition_id):
        version = request.args.get('version')
        new_location = redirect_to_last_update(definition_id, version)
        if new_location is not None:
            return new_location
        dataset = get_dataset(version=version)
        o = json.loads(dataset['data'])
        if not 'periodCollections' in o:
            abort(404)
        definition_key = prefix(definition_id)
        collection_key = prefix(definition_id[:5])
        if not collection_key in o['periodCollections']:
            abort(404)
        collection = o['periodCollections'][collection_key]

        if not definition_key in collection['definitions']:
            abort(404)
        definition = collection['definitions'][definition_key]
        definition['@context'] = o['@context']
        return  attach_to_dataset(definition)

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
    dataset = dataset or get_dataset()
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
        query += ' limit ' + str(limit + 1) + ' offset ' + str(offset)

        rows = query_db(query, params)
        data = [process_patch_row(row) for row in rows][:limit]

        link_headers = []

        if offset > 0:
            prev_url = url_for('patchlist', _external=True)

            prev_params = request.args.to_dict().copy()
            prev_params['from'] = offset - limit
            if (prev_params['from'] <= 0): prev_params.pop('from')

            prev_params = urlencode(prev_params)
            if (prev_params):
                prev_url += '?' + prev_params

            link_headers.append('<{}>; rel="prev"'.format(prev_url))

        # We fetched 1 more than the limit. If there are limit+1 rows in the
        # retrieved query, then there are more rows to be fetched
        if len(rows) > limit:
            next_url = url_for('patchlist', _external=True)
            next_params = request.args.to_dict().copy()

            next_params['from'] = offset + limit
            link_headers.append(
                '<{}?{}>; rel="next"'.format(next_url, urlencode(next_params)))


        headers = {}
        if (link_headers):
            headers['Link'] = ', '.join(link_headers)

        return marshal(data, patch_list_fields), 200, headers

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
        data['mergeable'] = is_mergeable(data['original_patch'])
        headers = {}

        try:
            if accept_patch_permission.can():
                headers['Link'] = '<{}>;rel="merge"'.format(url_for('patchmerge', id=id))
        except AuthenticationFailed:
            pass

        return marshal(data, patch_fields), 200, headers

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
            affected_entities = validate_patch(patch)
        except InvalidPatchException as e:
            if str(e) != 'Could not apply JSON patch to dataset.':
                return { 'status': 400, 'message': str(e) }, 400

        db = get_db()
        curs = db.cursor()
        curs.execute(
'''
UPDATE patch_request SET
original_patch = ?,
affected_entities = ?,
updated_by = ?
WHERE id = ?
''',
            (patch.to_string(), json.dumps(sorted(affected_entities)),
             g.identity.id, id)
        )
        db.commit()


@api.resource('/patches/<int:id>/merge')
class PatchMerge(Resource):
    @accept_patch_permission.require()
    def post(self, id):
        try:
            merge_patch(id, g.identity.id)
            return None, 204
        except MergeError as e:
            return {'message': e.message}, 404
        except UnmergeablePatchError as e:
            return {'message': e.message}, 400


class MergeError(Exception):
    def __init__(self, message):
        self.message = message


class UnmergeablePatchError(MergeError):
    pass


def merge_patch(patch_id, user_id):
    row = query_db(PATCH_QUERY + ' where id = ?', (patch_id,), one=True)

    if not row:
        raise MergeError('No patch with ID {}.'.format(patch_id))
    if row['merged']:
        raise MergeError('Patch is already merged.')
    if not row['open']:
        raise MergeError('Closed patches cannot be merged.')

    dataset = get_dataset()
    mergeable = is_mergeable(row['original_patch'], dataset)

    if not mergeable:
        raise UnmergeablePatchError('Patch is not mergeable.')

    data = json.loads(dataset['data'])
    original_patch = patch_from_text(row['original_patch'])
    applied_patch, new_ids = replace_skolem_ids(original_patch, data)
    affected_entities = (set(json.loads(row['affected_entities']))
                         | set(new_ids))

    # Should this be ordered?
    new_data = applied_patch.apply(data)

    db = get_db()
    curs = db.cursor()
    curs.execute(
        '''
        UPDATE patch_request
        SET merged = 1,
            open = 0,
            merged_at = CURRENT_TIMESTAMP,
            merged_by = ?,
            applied_to = ?,
            affected_entities = ?,
            applied_patch = ?
        WHERE id = ?;
        ''',
        (user_id,
         dataset['id'],
         json.dumps(sorted(affected_entities)),
         applied_patch.to_string(),
         row['id'])
    )
    add_new_version_of_dataset(curs, new_data)
    curs.execute(
        '''
        UPDATE patch_request
        SET resulted_in = ?
        WHERE id = ?;
        ''',
        (curs.lastrowid, row['id'])
    )
    curs.lastrowid
    db.commit()


def generate_state_token():
    return ''.join(random.choice(string.ascii_uppercase + string.digits)
                   for x in range(32))

@app.route('/register')
def register():
    state_token = generate_state_token()
    session['state_token'] = state_token
    params = {
        'client_id': ORCID_CLIENT_ID,
        'redirect_uri': url_for('registered', _external=True),
        'response_type': 'code',
        'scope': '/authenticate',
        'state': state_token,
    }
    return redirect(
        'https://orcid.org/oauth/authorize?{}'.format(urlencode(params)))

@app.route('/registered')
def registered():
    if not request.args['state'] == session.pop('state_token'):
        abort(403)
    data = {
        'client_id': ORCID_CLIENT_ID,
        'client_secret': ORCID_CLIENT_SECRET,
        'code': request.args['code'],
        'grant_type': 'authorization_code',
        'redirect_uri': url_for('registered', _external=True),
        'scope': '/authenticate',
    }
    response = requests.post(
        'https://pub.orcid.org/oauth/token',
        headers={'Accept': 'application/json'},
        allow_redirects=True, data=data)
    credentials = response.json()
    identity = add_user_or_update_credentials(credentials)
    return make_response(
        """
        <!doctype html>
        <head>
            <script type="text/javascript">
            localStorage.auth = '{}';
            window.close();
            </script>
        </head>
        <body>
        """.format(json.dumps(
            { 'name': credentials['name'], 'token': identity.b64token.decode() }
        )))

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
        with open(datafile) as f:
            data = json.load(f)
        user_id = 'initial-data-loader'
        patch = JsonPatch.from_diff({}, data)
        patch_request_id = create_patch_request(patch, user_id)
        merge_patch(patch_request_id, user_id)


def get_db():
    db = getattr(g, '_database', None)
    if db is None:
        db = g._database = sqlite3.connect(app.config['DATABASE'])
        db.row_factory = sqlite3.Row
    return db

def query_db(query, args=(), one=False, cursor=None):
    curs = cursor if cursor else get_db().cursor()
    curs.execute(query, args)
    rows = curs.fetchall()
    if not cursor: curs.close()
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
