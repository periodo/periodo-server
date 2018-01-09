import json
from collections import OrderedDict
from flask import request, g, abort, url_for, redirect
from flask_restful import fields, Resource, marshal, marshal_with, reqparse
from periodo import api, database, auth, identifier, patching, utils, nanopub
from urllib.parse import urlencode

from wsgiref.handlers import format_date_time

PATCH_QUERY = """
SELECT *
FROM patch_request
"""

index_fields = {
    'dataset': fields.Url('dataset', absolute=True),
    'dataset_description': fields.Url('void', absolute=True),
    'patches': fields.Url('patchlist', absolute=True),
    'register': fields.Url('register', absolute=True),
}


# http://www.w3.org/TR/NOTE-datetime
class W3CDTF(fields.Raw):
    def format(self, value):
        return utils.isoformat(value)


patch_list_fields = OrderedDict((
    ('url', fields.Url('patchrequest', absolute=True)),
    ('created_by', fields.String),
    ('created_at', W3CDTF),
    ('updated_by', fields.String),
    ('updated_at', W3CDTF),
    ('created_from', fields.String),
    ('applied_to', fields.String),
    ('identifier_map', fields.Raw),
    ('text', fields.Url('patch', absolute=True)),
    ('open', fields.Boolean),
    ('merged', fields.Boolean)
))

comment_fields = OrderedDict((
    ('author', fields.String),
    ('posted_at', W3CDTF),
    ('message', fields.String)
))

patch_fields = patch_list_fields.copy()
patch_fields.update((
    ('mergeable', fields.Boolean),
    ('comments', fields.List(fields.Nested(comment_fields))),
))

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

versioned_parser = reqparse.RequestParser()
versioned_parser.add_argument(
    'version', type=int, location='args', help='Invalid version number')


def cache_control(args):
    return 'public, max-age={}'.format(604800 if args['version'] else 0)


def attach_to_dataset(o):
    if len(o) > 0:
        o['primaryTopicOf'] = {'id': identifier.prefix(request.path[1:]),
                               'inDataset': identifier.prefix('d')}
    return o


def redirect_to_last_update(entity_id, version):
    if version is None:
        return None
    v = database.find_version_of_last_update(
        identifier.prefix(entity_id), version)
    if v is None:
        abort(404)
    if v == int(version):
        return None
    return redirect(request.path + '?version={}'.format(v), code=301)


def make_dataset_url(version):
    return url_for('dataset', _external=True) + '?version=' + str(version)


def process_patch_row(row):
    d = dict(row)
    d['created_from'] = make_dataset_url(row['created_from'])
    d['applied_to'] = make_dataset_url(
        row['created_from']) if row['applied_to'] else None
    d['identifier_map'] = json.loads(
        row['identifier_map']) if row['identifier_map'] else None
    return d


def abort_gone_or_not_found(entity_key):
    if entity_key in database.get_removed_entity_keys():
        abort(410)
    else:
        abort(404)


def get_dataset(version=None):
    dataset = database.get_dataset(version)

    if not dataset:
        if version:
            raise ResourceError(404, 'Could not find given version.')
        else:
            raise ResourceError(501, 'No dataset loaded yet.')

    return dataset


class ResourceError(Exception):
    def __init__(self, status, message):
        self.status = status
        self.message = message

    def response(self):
        return {'status': self.status, 'message': self.message}, self.status


@api.resource('/')
class Index(Resource):
    @marshal_with(index_fields)
    def get(self):
        return {}


@api.resource('/c', endpoint='context')
@api.resource('/c.json', endpoint='context-json')
@api.resource('/c.json.html', endpoint='context-json-html')
class Context(Resource):
    def get(self):
        args = versioned_parser.parse_args()

        try:
            dataset = get_dataset(args.get('version', None))
        except ResourceError as e:
            return e.response()

        context_etag = 'periodo-context-version-{}'.format(dataset['id'])
        if request.if_none_match.contains_weak(context_etag):
            return None, 304

        headers = {}
        headers['Last-Modified'] = format_date_time(dataset['created_at'])
        headers['Cache_Control'] = cache_control(args)

        context = json.loads(dataset['data']).get('@context', None)
        if context is None:
            return None, 404

        response = api.make_response({'@context': context}, 200, headers)
        response.set_etag(context_etag, weak=True)

        return response


@api.resource('/d/', '/d.json', '/d.jsonld')
class Dataset(Resource):
    def get(self):
        args = versioned_parser.parse_args()
        version = args.get('version', None)

        try:
            dataset = get_dataset(version)
        except ResourceError as e:
            return e.response()

        dataset_etag = 'periodo-dataset-version-{}'.format(dataset['id'])
        if request.if_none_match.contains_weak(dataset_etag):
            return None, 304

        headers = {}
        headers['Last-Modified'] = format_date_time(dataset['created_at'])
        headers['Cache_Control'] = cache_control(args)

        data = json.loads(dataset['data'])
        if version is not None and '@context' in data:
            data['@context']['__version'] = version
        if 'inline-context' in request.args:
            data['@context']['__inline'] = True

        response = api.make_response(attach_to_dataset(data), 200, headers)
        response.set_etag(dataset_etag, weak=True)

        return response

    @auth.submit_patch_permission.require()
    def patch(self):
        try:
            patch_request_id = patching.create_request(
                patching.from_text(request.data), g.identity.id)
            database.commit()
            return None, 202, {
                'Location': api.url_for(PatchRequest, id=patch_request_id)
            }
        except patching.InvalidPatchError as e:
            return {'status': 400, 'message': str(e)}, 400


@api.resource('/<string(length=%s):collection_id>.json'
              % (identifier.COLLECTION_SEQUENCE_LENGTH + 1),
              endpoint='collection-json')
@api.resource('/<string(length=%s):collection_id>.jsonld'
              % (identifier.COLLECTION_SEQUENCE_LENGTH + 1),
              endpoint='collection-jsonld')
@api.resource('/<string(length=%s):collection_id>.ttl'
              % (identifier.COLLECTION_SEQUENCE_LENGTH + 1),
              endpoint='collection-ttl')
@api.resource('/<string(length=%s):collection_id>.json.html'
              % (identifier.COLLECTION_SEQUENCE_LENGTH + 1),
              endpoint='collection-json-html')
@api.resource('/<string(length=%s):collection_id>.jsonld.html'
              % (identifier.COLLECTION_SEQUENCE_LENGTH + 1),
              endpoint='collection-jsonld-html')
@api.resource('/<string(length=%s):collection_id>.ttl.html'
              % (identifier.COLLECTION_SEQUENCE_LENGTH + 1),
              endpoint='collection-ttl-html')
class PeriodCollection(Resource):
    def get(self, collection_id):
        version = request.args.get('version')
        new_location = redirect_to_last_update(collection_id, version)
        if new_location is not None:
            return new_location
        try:
            return attach_to_dataset(
                database.get_collection(collection_id, version))
        except database.MissingKeyError as e:
            abort_gone_or_not_found(e.key)


@api.resource('/<string(length=%s):definition_id>.json'
              % (identifier.COLLECTION_SEQUENCE_LENGTH + 1 +
                 identifier.DEFINITION_SEQUENCE_LENGTH + 1),
              endpoint='definition-json')
@api.resource('/<string(length=%s):definition_id>.jsonld'
              % (identifier.COLLECTION_SEQUENCE_LENGTH + 1 +
                 identifier.DEFINITION_SEQUENCE_LENGTH + 1),
              endpoint='definition-jsonld')
@api.resource('/<string(length=%s):definition_id>.ttl'
              % (identifier.COLLECTION_SEQUENCE_LENGTH + 1 +
                 identifier.DEFINITION_SEQUENCE_LENGTH + 1),
              endpoint='definition-ttl')
@api.resource('/<string(length=%s):definition_id>.json.html'
              % (identifier.COLLECTION_SEQUENCE_LENGTH + 1 +
                 identifier.DEFINITION_SEQUENCE_LENGTH + 1),
              endpoint='definition-json-html')
@api.resource('/<string(length=%s):definition_id>.jsonld.html'
              % (identifier.COLLECTION_SEQUENCE_LENGTH + 1 +
                 identifier.DEFINITION_SEQUENCE_LENGTH + 1),
              endpoint='definition-jsonld-html')
@api.resource('/<string(length=%s):definition_id>.ttl.html'
              % (identifier.COLLECTION_SEQUENCE_LENGTH + 1 +
                 identifier.DEFINITION_SEQUENCE_LENGTH + 1),
              endpoint='definition-ttl-html')
class PeriodDefinition(Resource):
    def get(self, definition_id):
        version = request.args.get('version')
        new_location = redirect_to_last_update(definition_id, version)
        if new_location is not None:
            return new_location
        try:
            return attach_to_dataset(
                database.get_definition(definition_id, version))
        except database.MissingKeyError as e:
            abort_gone_or_not_found(e.key)


@api.resource('/<string(length=%s):definition_id>/nanopub<int:version>'
              % (identifier.COLLECTION_SEQUENCE_LENGTH + 1 +
                 identifier.DEFINITION_SEQUENCE_LENGTH + 1),
              endpoint='definition-nanopub')
class PeriodNanopublication(Resource):
    def get(self, definition_id, version):
        return nanopub.make_nanopub(definition_id, version)


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
        if limit < 0:
            limit = 25
        if limit > 250:
            limit = 250

        offset = args['from']
        if offset < 0:
            offset = 0
        query += ' limit ' + str(limit + 1) + ' offset ' + str(offset)

        rows = database.query_db(query, params)
        data = [process_patch_row(row) for row in rows][:limit]

        link_headers = []

        if offset > 0:
            prev_url = url_for('patchlist', _external=True)

            prev_params = request.args.to_dict().copy()
            prev_params['from'] = offset - limit
            if (prev_params['from'] <= 0):
                prev_params.pop('from')

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


@api.resource('/patches/<int:id>/')
class PatchRequest(Resource):
    def get(self, id):
        row = database.query_db(PATCH_QUERY + ' where id = ?', (id,), one=True)
        if not row:
            abort(404)
        data = process_patch_row(row)
        data['mergeable'] = patching.is_mergeable(data['original_patch'])
        headers = {}

        comments = database.query_db(
            '''
            SELECT author, message, posted_at
            FROM patch_request_comment
            WHERE patch_request_id=?
            ORDER BY posted_at ASC
            ''',
            (id,)
        )
        data['comments'] = [dict(row) for row in comments]

        try:
            if auth.accept_patch_permission.can():
                headers['Link'] = '<{}>;rel="merge"'.format(
                    url_for('patchmerge', id=id))
        except auth.AuthenticationFailed:
            pass

        return marshal(data, patch_fields), 200, headers


@api.resource('/patches/<int:id>/patch.jsonpatch')
class Patch(Resource):
    def get(self, id):
        row = database.query_db(PATCH_QUERY + ' where id = ?', (id,), one=True)
        if row['merged']:
            p = row['applied_patch']
        else:
            p = row['original_patch']
        return json.loads(p), 200

    def put(self, id):
        permission = auth.UpdatePatchPermission(id)
        if not permission.can():
            raise auth.PermissionDenied(permission)
        try:
            patch = patching.from_text(request.data)
            affected_entities = patching.validate(
                patch, database.get_dataset())
        except patching.InvalidPatchError as e:
            if str(e) != 'Could not apply JSON patch to dataset.':
                return {'status': 400, 'message': str(e)}, 400

        db = database.get_db()
        curs = db.cursor()
        curs.execute('''
UPDATE patch_request SET
original_patch = ?,
updated_entities = ?,
removed_entities = ?,
updated_by = ?
WHERE id = ?
        ''', (patch.to_string(),
              json.dumps(sorted(affected_entities['updated'])),
              json.dumps(sorted(affected_entities['removed'])),
              g.identity.id, id)
        )
        db.commit()


@api.resource('/patches/<int:id>/merge')
class PatchMerge(Resource):
    @auth.accept_patch_permission.require()
    def post(self, id):
        try:
            patching.merge(id, g.identity.id)
            database.commit()
            return None, 204
        except patching.MergeError as e:
            return {'message': e.message}, 404
        except patching.UnmergeablePatchError as e:
            return {'message': e.message}, 400


@api.resource('/patches/<int:id>/reject')
class PatchReject(Resource):
    @auth.accept_patch_permission.require()
    def post(self, id):
        try:
            patching.reject(id, g.identity.id)
            database.commit()
            return None, 204
        except patching.MergeError as e:
            return {'message': e.message}, 404


@api.resource('/patches/<int:id>/messages')
class PatchMessages(Resource):
    @auth.submit_patch_permission.require()
    def post(self, id):
        data = request.data or ''
        if isinstance(data, bytes):
            data = data.decode()

        try:
            data = json.loads(data)
            message = data['message']
        except:
            return {'message': 'No message present in request data.'}, 400

        try:
            patching.add_comment(id,
                                 g.identity.id,
                                 message)
            database.commit()
            return None, 200, {
                'Location': api.url_for(PatchRequest, id=id)
            }
        except patching.MergeError as e:
            return {'message': e.message}, 404


@api.resource('/bags/<uuid:uuid>')
class Bag(Resource):
    @auth.update_bag_permission.require()
    def put(self, uuid):

        data = request.get_json()

        title = str(data.get('title', ''))
        if len(title) == 0:
            return {'message': 'A bag must have a title'}, 400

        items = data.get('items', [])
        if len(items) < 2:
            return {'message': 'A bag must have at least two items'}, 400

        try:
            defs, ctx = database.\
                        get_definitions_and_context(items, raiseErrors=True)
        except database.MissingKeyError as e:
            return {'message': 'No resource with key: ' + e.key}, 400

        base = ctx['@base']
        bag_ctx = data.get('@context', {})
        if type(bag_ctx) is list:
            contexts = bag_ctx
            if (base + 'p0c') not in contexts:
                contexts.insert(0, base + 'p0c')
            if type(contexts[-1]) is dict:
                contexts[-1]['@base'] = base
            else:
                contexts.append({'@base': base})
        else:
            contexts = [base + 'p0c', {**bag_ctx, '@base': base}]

        data['@context'] = contexts

        bag = database.get_bag(uuid)
        if bag and g.identity.id not in json.loads(bag['owners']):
            return None, 403

        version = database.create_or_update_bag(uuid, g.identity.id, data)
        return None, 201, {
            'Location': api.url_for(Bag, uuid=uuid, version=version)
        }

    def get(self, uuid):
        args = versioned_parser.parse_args()
        bag = database.get_bag(uuid, version=args.get('version', None))

        if not bag:
            abort(404)

        bag_etag = 'bag-{}-version-{}'.format(uuid, bag['version'])
        if request.if_none_match.contains_weak(bag_etag):
            return None, 304

        headers = {}
        headers['Last-Modified'] = format_date_time(bag['created_at'])
        headers['Cache_Control'] = cache_control(args)

        data = json.loads(bag['data'])
        defs, defs_ctx = database.get_definitions_and_context(data['items'])

        data['@id'] = identifier.prefix('bags/%s' % uuid)
        data['creator'] = bag['created_by']
        data['items'] = defs

        response = api.make_response(data, 200, headers)
        response.set_etag(bag_etag, weak=True)
        return response
