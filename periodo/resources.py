import datetime
import json
from collections import OrderedDict
from email.utils import parsedate
from flask import request, g, abort, url_for, redirect
from flask.ext.restful import fields, Resource, marshal, marshal_with, reqparse
from periodo import api, database, auth, identifier, patching
from time import mktime
from urllib.parse import urlencode

from wsgiref.handlers import format_date_time

ISO_TIME_FMT = '%Y-%m-%d %H:%M:%S'

index_fields = {
    'dataset': fields.Url('dataset', absolute=True),
    'patches': fields.Url('patchlist', absolute=True),
    'register': fields.Url('register', absolute=True),
}


dataset_parser = reqparse.RequestParser()
dataset_parser.add_argument(
    'If-Modified-Since', dest='modified', location='headers')
dataset_parser.add_argument('version', type=int, location='args',
                            help='Invalid version number')


def attach_to_dataset(o):
    o['primaryTopicOf'] = {'id': identifier.prefix(request.path[1:]),
                           'inDataset': identifier.prefix('d')}
    return o


def iso_to_timestamp(iso_timestr, fmt=ISO_TIME_FMT):
    dt = datetime.datetime.strptime(iso_timestr, fmt)
    return mktime(dt.timetuple())


@api.resource('/')
class Index(Resource):
    @marshal_with(index_fields)
    def get(self):
        return {}


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

        dataset = database.query_db(query, query_args, one=True)

        if not dataset:
            if args['version']:
                return {'status': 404,
                        'message': 'Could not find given version.'}, 404
            else:
                return {'status': 501,
                        'message': 'No dataset loaded yet.'}, 501

        last_modified = iso_to_timestamp(dataset['created'])
        modified_check = mktime(parsedate(
            args['modified'])) if args['modified'] else 0

        if modified_check >= last_modified:
            return None, 304

        return attach_to_dataset(json.loads(dataset['data'])), 200, {
            'Last-Modified': format_date_time(last_modified)}

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


@api.resource('/<string(length=%s):collection_id>.json'
              % (identifier.COLLECTION_SEQUENCE_LENGTH + 1),
              endpoint='collection-json')
@api.resource('/<string(length=%s):collection_id>.jsonld'
              % (identifier.COLLECTION_SEQUENCE_LENGTH + 1),
              endpoint='collection-jsonld')
class PeriodCollection(Resource):
    def get(self, collection_id):
        version = request.args.get('version')
        new_location = redirect_to_last_update(collection_id, version)
        if new_location is not None:
            return new_location
        dataset = database.get_dataset(version=version)
        o = json.loads(dataset['data'])
        if 'periodCollections' not in o:
            abort(404)
        collection_key = identifier.prefix(collection_id)
        if collection_key not in o['periodCollections']:
            abort(404)
        collection = o['periodCollections'][collection_key]
        collection['@context'] = o['@context']
        return attach_to_dataset(collection)


@api.resource('/<string(length=%s):definition_id>.json'
              % (identifier.COLLECTION_SEQUENCE_LENGTH + 1 +
                 identifier.DEFINITION_SEQUENCE_LENGTH + 1),
              endpoint='definition-json')
@api.resource('/<string(length=%s):definition_id>.jsonld'
              % (identifier.COLLECTION_SEQUENCE_LENGTH + 1 +
                 identifier.DEFINITION_SEQUENCE_LENGTH + 1),
              endpoint='definition-jsonld')
class PeriodDefinition(Resource):
    def get(self, definition_id):
        version = request.args.get('version')
        new_location = redirect_to_last_update(definition_id, version)
        if new_location is not None:
            return new_location
        dataset = database.get_dataset(version=version)
        o = json.loads(dataset['data'])
        if 'periodCollections' not in o:
            abort(404)
        definition_key = identifier.prefix(definition_id)
        collection_key = identifier.prefix(definition_id[:5])
        if collection_key not in o['periodCollections']:
            abort(404)
        collection = o['periodCollections'][collection_key]

        if definition_key not in collection['definitions']:
            abort(404)
        definition = collection['definitions'][definition_key]
        definition['@context'] = o['@context']
        return attach_to_dataset(definition)

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


def make_dataset_url(version):
    return url_for('dataset', _external=True) + '?version=' + str(version)


def process_patch_row(row):
    d = dict(row)
    d['created_from'] = make_dataset_url(row['created_from'])
    d['applied_to'] = make_dataset_url(
        row['created_from']) if row['applied_to'] else None
    return d


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

patch_fields = patch_list_fields.copy()
patch_fields.update((
    ('mergeable', fields.Boolean),
))


@api.resource('/patches/<int:id>/')
class PatchRequest(Resource):
    def get(self, id):
        row = database.query_db(PATCH_QUERY + ' where id = ?', (id,), one=True)
        if not row:
            abort(404)
        data = process_patch_row(row)
        data['mergeable'] = patching.is_mergeable(data['original_patch'])
        headers = {}

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
affected_entities = ?,
updated_by = ?
WHERE id = ?
        ''', (patch.to_string(), json.dumps(sorted(affected_entities)),
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