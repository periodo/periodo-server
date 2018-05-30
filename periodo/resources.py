import json
from collections import OrderedDict
from flask import request, g, abort, url_for, redirect
from flask_restful import fields, Resource, marshal, reqparse
from periodo import (
    app, api, cache, database, auth, identifier, patching,
    utils, nanopub, provenance)
from urllib.parse import urlencode
from wsgiref.handlers import format_date_time

PATCH_QUERY = """
SELECT *
FROM patch_request
"""


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


def attach_to_dataset(o):
    if len(o) > 0:
        if app.config['CANONICAL']:
            o['primaryTopicOf'] = {
                'id': identifier.prefix(request.full_path[1:]),
                'inDataset': {
                    'id': identifier.prefix('d'),
                    'changes': identifier.prefix('h#changes')
                }
            }
        else:
            o['primaryTopicOf'] = {
                'id': request.url,
                'inDataset': {
                    'id': url_for('abstract_dataset', _external=True),
                    'changes': url_for('history', _external=True) + '#changes'
                }
            }
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


INDEX = {
    'dataset':
    'the PeriodO dataset',

    'description':
    'description of the PeriodO dataset',

    'patches':
    'patches submitted to the PeriodO dataset',

    'history':
    'history of changes to the PeriodO dataset',

    'bags':
    'user-defined subsets of the PeriodO dataset',

    'context':
    'PeriodO JSON-LD context',

    'vocabulary':
    'PeriodO RDF vocabulary',
}


# decorator to add content-type-specific resources for each resource class
def add_resources(
        name,
        shortname=None,
        endpoint=None,
        barepaths=[],
        suffixes=('json', 'jsonld', 'ttl'),
        html=True
):
    def decorator(cls):

        paths = ['/{}'.format(name)]
        if shortname is not None:
            paths.insert(0, '/{}'.format(shortname))

        if barepaths is not None:
            api.add_resource(
                cls,
                *(paths if len(barepaths) == 0 else barepaths),
                endpoint=(endpoint or name))

        for suffix in suffixes:
            suffixed_paths = ['{}.{}'.format(p, suffix) for p in paths]
            suffixed_endpoint = '{}-{}'.format(endpoint or name, suffix)
            api.add_resource(
                cls,
                *suffixed_paths,
                endpoint=suffixed_endpoint)

            if html:
                api.add_resource(
                    cls,
                    *['{}.html'.format(p) for p in suffixed_paths],
                    endpoint='{}-html'.format(suffixed_endpoint))

        return cls

    return decorator


def describe_endpoint(endpoint, description):
    return {
        'description': description,
        'url': url_for(endpoint, _external=True)
    }


@add_resources('index', suffixes=['json'], barepaths=['/'])
class Index(Resource):
    def get(self):
        return {
            endpoint: describe_endpoint(endpoint, description)
            for (endpoint, description) in INDEX.items()
        }


@add_resources('context', shortname='c', suffixes=['json'])
class Context(Resource):
    def get(self):
        args = versioned_parser.parse_args()
        version = args.get('version')

        try:
            dataset = get_dataset(version)
        except ResourceError as e:
            return e.response()

        context_etag = 'periodo-context-version-{}'.format(dataset['id'])
        if request.if_none_match.contains_weak(context_etag):
            return None, 304

        headers = {}
        headers['Last-Modified'] = format_date_time(dataset['created_at'])

        context = json.loads(dataset['data']).get('@context')
        if context is None:
            return None, 404

        response = api.make_response({'@context': context}, 200, headers)
        response.set_etag(context_etag, weak=True)

        if version is None:
            return cache.no_time(response)
        else:
            return cache.long_time(response)


@add_resources('dataset', shortname='d', barepaths=['/d/'], html=False)
class Dataset(Resource):
    def get(self):
        args = versioned_parser.parse_args()
        version = args.get('version')
        filename = 'periodo-dataset{}'.format(
            '' if version is None else '-v{}'.format(version))

        try:
            dataset = get_dataset(version)
        except ResourceError as e:
            return e.response()

        dataset_etag = 'periodo-dataset-version-{}'.format(dataset['id'])
        if request.if_none_match.contains_weak(dataset_etag):
            return None, 304

        headers = {}
        headers['Last-Modified'] = format_date_time(dataset['created_at'])

        data = json.loads(dataset['data'])
        if version is not None and '@context' in data:
            data['@context']['__version'] = version
        if 'inline-context' in request.args:
            data['@context']['__inline'] = True

        response = api.make_response(
            attach_to_dataset(data), 200, headers, filename=filename)
        response.set_etag(dataset_etag, weak=True)

        if version is None:
            return cache.short_time(response, server_only=True)
        else:
            return cache.long_time(response)

    @auth.submit_patch_permission.require()
    def patch(self):
        try:
            patch_request_id = patching.create_request(
                patching.from_text(request.data), g.identity.id)
            database.commit()
            return None, 202, {
                'Location': url_for('patchrequest', id=patch_request_id)
            }
        except patching.InvalidPatchError as e:
            return {'status': 400, 'message': str(e)}, 400


@add_resources('history', shortname='h', barepaths=None, html=False)
class History(Resource):
    def get(self):
        response = api.make_response(
            provenance.history('inline-context' in request.args),
            200, filename='periodo-history'
        )
        return cache.medium_time(response, server_only=True)


@add_resources(
    '<string(length={}):authority_id>'.format(
        identifier.AUTHORITY_SEQUENCE_LENGTH + 1),
    endpoint='authority',
    barepaths=None)
class Authority(Resource):
    def get(self, authority_id):
        version = request.args.get('version')
        new_location = redirect_to_last_update(authority_id, version)
        if new_location is not None:
            return new_location
        try:
            authority = attach_to_dataset(
                database.get_authority(authority_id, version))
            filename = 'periodo-authority-{}{}'.format(
                authority_id,
                '' if version is None else '-v{}'.format(version))
            return api.make_response(authority, 200, filename=filename)
        except database.MissingKeyError as e:
            abort_gone_or_not_found(e.key)


@add_resources(
    '<string(length={}):definition_id>'.format(
        identifier.AUTHORITY_SEQUENCE_LENGTH + 1 +
        identifier.DEFINITION_SEQUENCE_LENGTH + 1),
    endpoint='definition',
    barepaths=None)
class PeriodDefinition(Resource):
    def get(self, definition_id):
        version = request.args.get('version')
        new_location = redirect_to_last_update(definition_id, version)
        if new_location is not None:
            return new_location
        try:
            definition = attach_to_dataset(
                database.get_definition(definition_id, version))
            filename = 'periodo-definition-{}{}'.format(
                definition_id,
                '' if version is None else '-v{}'.format(version))
            return api.make_response(definition, 200, filename=filename)
        except database.MissingKeyError as e:
            abort_gone_or_not_found(e.key)


@api.resource('/<string(length=%s):definition_id>/nanopub<int:version>'
              % (identifier.AUTHORITY_SEQUENCE_LENGTH + 1 +
                 identifier.DEFINITION_SEQUENCE_LENGTH + 1),
              endpoint='definition-nanopub')
class PeriodNanopublication(Resource):
    def get(self, definition_id, version):
        return nanopub.make_nanopub(definition_id, version)


@add_resources('patches', suffixes=['json'], barepaths=['/patches/'])
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
            prev_url = url_for('patches', _external=True)

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
            next_url = url_for('patches', _external=True)
            next_params = request.args.to_dict().copy()

            next_params['from'] = offset + limit
            link_headers.append(
                '<{}?{}>; rel="next"'.format(next_url, urlencode(next_params)))

        headers = {}
        if (link_headers):
            headers['Link'] = ', '.join(link_headers)

        return marshal(data, patch_list_fields), 200, headers


@add_resources(
    'patches/<int:id>',
    endpoint='patchrequest',
    suffixes=['json'],
    barepaths=['/patches/<int:id>/'])
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


@add_resources(
    'patches/<int:id>/patch',
    endpoint='patch',
    suffixes=['json'],
    barepaths=['/patches/<int:id>/patch.jsonpatch'])
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
            cache.purge_history()
            cache.purge_dataset()
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
                'Location': url_for('patchrequest', id=id)
            }
        except patching.MergeError as e:
            return {'message': e.message}, 404


@add_resources('bags', suffixes=['json'], barepaths=['/bags/'])
class Bags(Resource):
    def get(self):
        return [
            url_for('bag', uuid=uuid, _external=True)
            for uuid in database.get_bag_uuids()
        ]


@add_resources('bags/<uuid:uuid>', endpoint='bag', suffixes=['json'])
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
        context_url = utils.absolute_url(ctx['@base'], 'context')
        if type(bag_ctx) is list:
            contexts = bag_ctx
            if context_url not in contexts:
                contexts.insert(0, context_url)
            if type(contexts[-1]) is dict:
                contexts[-1]['@base'] = base
            else:
                contexts.append({'@base': base})
        else:
            contexts = [context_url, {**bag_ctx, '@base': base}]

        data['@context'] = contexts

        bag = database.get_bag(uuid)
        if bag and g.identity.id not in json.loads(bag['owners']):
            return None, 403

        version = database.create_or_update_bag(uuid, g.identity.id, data)
        return None, 201, {
            'Location': url_for('bag', uuid=uuid, version=version)
        }

    def get(self, uuid):
        args = versioned_parser.parse_args()
        version = args.get('version')
        bag = database.get_bag(uuid, version=version)

        if not bag:
            abort(404)

        bag_etag = 'bag-{}-version-{}'.format(uuid, bag['version'])
        if request.if_none_match.contains_weak(bag_etag):
            return None, 304

        headers = {}
        headers['Last-Modified'] = format_date_time(bag['created_at'])

        data = json.loads(bag['data'])
        defs, defs_ctx = database.get_definitions_and_context(data['items'])

        data['@id'] = identifier.prefix('bags/%s' % uuid)
        data['creator'] = bag['created_by']
        data['items'] = defs

        response = api.make_response(data, 200, headers)
        response.set_etag(bag_etag, weak=True)

        if version is None:
            return cache.no_time(response)
        else:
            return cache.long_time(response)
