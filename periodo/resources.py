import json
from collections import OrderedDict
from flask import request, g, abort, url_for, redirect
from flask_restful import fields, Resource, marshal, reqparse
from jsonpatch import JsonPatch
from periodo import (
    app, api, cache, database, auth, identifier, patching,
    utils, nanopub, provenance)
from urllib.parse import urlencode
from wsgiref.handlers import format_date_time

PATCH_QUERY = """
SELECT patch_request.*, comment.message AS first_comment
FROM patch_request
LEFT JOIN (
  SELECT patch_request_id, message
  FROM patch_request_comment
  WHERE id IN (
    SELECT MIN(id)
    FROM patch_request_comment
    GROUP BY patch_request_id
  )
)
AS comment
ON comment.patch_request_id = patch_request.id
"""


# http://www.w3.org/TR/NOTE-datetime
class W3CDTF(fields.Raw):
    def format(self, value):
        return utils.isoformat(value)


patch_list_url_fields = OrderedDict((
    ('url', fields.Url('patchrequest', absolute=True)),
    ('text', fields.Url('patch', absolute=True)),
))

patch_list_fields = OrderedDict((
    ('created_by', fields.String),
    ('created_at', W3CDTF),
    ('updated_by', fields.String),
    ('updated_at', W3CDTF),
    ('created_from', fields.String),
    ('applied_to', fields.String),
    ('identifier_map', fields.Raw),
    ('open', fields.Boolean),
    ('merged', fields.Boolean),
    ('first_comment', fields.String),
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

patch_url_fields = patch_list_url_fields.copy()

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


def parse_json(request):
    try:
        return json.loads(request.get_data(as_text=True))
    except json.JSONDecodeError:
        raise ResourceError(400, 'Request data could not be parsed as JSON.')


def attach_to_dataset(o):
    if len(o) > 0:
        if app.config['CANONICAL']:
            path = request.full_path[1:]
            if path.endswith('?'):
                path = path[:-1]
            o['primaryTopicOf'] = {
                'id': identifier.prefix(path),
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
    'client':
    'PeriodO client (browse and edit periods)',

    'dataset':
    'PeriodO dataset',

    'description':
    'description of the PeriodO dataset',

    'patches':
    'patches submitted to the PeriodO dataset',

    'history':
    'history of changes to the PeriodO dataset',

    'bags':
    'user-defined subsets of the PeriodO dataset',

    'identifier-map':
    'a map of skolem IRIs that have been replaced with persistent IRIs',

    'context':
    'PeriodO JSON-LD context',

    'vocabulary':
    'PeriodO RDF vocabulary',

    'client-packages':
    'PeriodO client installation packages',
}


# decorator to add content-type-specific resources for each resource class
def add_resources(
        name,
        shortname=None,
        endpoint=None,
        barepaths=[],
        suffixes=('json', 'jsonld', 'ttl', 'csv'),
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
        'url': (url_for(endpoint, _external=True)
                if not endpoint == 'client' else app.config['CLIENT_URL'])
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
                JsonPatch(parse_json(request)), g.identity.id)
            database.commit()
            return None, 202, {
                'Location': url_for('patchrequest', id=patch_request_id)
            }
        except ResourceError as e:
            return e.response()
        except patching.InvalidPatchError as e:
            return {'status': 400, 'message': str(e)}, 400


@add_resources(
    'history',
    shortname='h',
    barepaths=None,
    suffixes=('nt',),
    html=False)
class History(Resource):
    def get(self):
        response = api.make_response(
            provenance.history(
                include_entity_details=('full' in request.args)
            ),
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
    '<string(length={}):period_id>'.format(
        identifier.AUTHORITY_SEQUENCE_LENGTH + 1 +
        identifier.PERIOD_SEQUENCE_LENGTH + 1),
    endpoint='period',
    barepaths=None)
class Period(Resource):
    def get(self, period_id):
        version = request.args.get('version')
        new_location = redirect_to_last_update(period_id, version)
        if new_location is not None:
            return new_location
        try:
            period = attach_to_dataset(
                database.get_period(period_id, version))
            filename = 'periodo-period-{}{}'.format(
                period_id,
                '' if version is None else '-v{}'.format(version))
            return api.make_response(period, 200, filename=filename)
        except database.MissingKeyError as e:
            abort_gone_or_not_found(e.key)


@api.resource('/<string(length=%s):period_id>/nanopub<int:version>'
              % (identifier.AUTHORITY_SEQUENCE_LENGTH + 1 +
                 identifier.PERIOD_SEQUENCE_LENGTH + 1),
              endpoint='period-nanopub')
class PeriodNanopublication(Resource):
    def get(self, period_id, version):
        return nanopub.make_nanopub(period_id, version)


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

        count_rows = database.query_db(
            """
            SELECT COUNT(*) AS count FROM patch_request
            """)

        count = count_rows[0]['count']

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

        headers['X-Total-Count'] = count

        marshaled_non_url = marshal(data, patch_list_fields)

        # Separating out marshaling the URLs from everything else because
        # it takes a very long time to do it otherwise. In reversing the URL,
        # flask_restful passes the whole dataobject to werkzeug's url reversing
        # function, requiring that every character of that object be URL
        # escaped. This actually creates a huge amount of overhead for larger
        # objects, like patch requests with lots of ID mappings. So, we marshal
        # these fields differently, only passing the ID field (which is all
        # that is needed to reverse the URL).
        ids = [{'id': item['id']} for item in data]
        marshaled = marshal(ids, patch_list_url_fields)

        # Once that's done, merge everything into the URL fields
        for i, d in enumerate(marshaled):
            d.update(marshaled_non_url[i])

        return marshaled, 200, headers


@add_resources(
    'patches/<int:id>',
    endpoint='patchrequest',
    suffixes=['json'],
    barepaths=['/patches/<int:id>/'])
class PatchRequest(Resource):
    def get(self, id):
        row = database.query_db(
            PATCH_QUERY + ' where patch_request.id = ?', (id,), one=True)
        if not row:
            abort(404)
        data = process_patch_row(row)
        data['mergeable'] = patching.is_mergeable(data['original_patch'])
        data['comments'] = [dict(c) for c in
                            database.get_patch_request_comments(id)]
        headers = {}
        try:
            if auth.accept_patch_permission.can():
                headers['Link'] = '<{}>;rel="merge"'.format(
                    url_for('patchmerge', id=id))
        except auth.AuthenticationFailed:
            pass

        # See patch list field for details about this dance
        marshaled_non_url = marshal(data, patch_fields)
        marshaled = marshal({'id': data['id']}, patch_url_fields)
        marshaled.update(marshaled_non_url)

        return marshaled, 200, headers


@add_resources(
    'patches/<int:id>/patch',
    endpoint='patch',
    suffixes=['json'],
    barepaths=['/patches/<int:id>/patch.jsonpatch'])
class Patch(Resource):
    def get(self, id):
        row = database.query_db(
            PATCH_QUERY + ' where patch_request.id = ?', (id,), one=True)
        if not row:
            abort(404)
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
            patch = JsonPatch(parse_json(request))
            affected_entities = patching.validate(
                patch, database.get_dataset())
        except ResourceError as e:
            return e.response()
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
            cache.purge_graphs()
            return None, 204
        except patching.UnmergeablePatchError as e:
            return {'message': e.message}, 400
        except patching.MergeError as e:
            return {'message': e.message}, 404


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
        except KeyError:
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


@add_resources('identifier-map', suffixes=['json'],
               barepaths=['/identifier-map/'])
class IdentifierMap(Resource):
    def get(self):
        identifier_map, last_edited = database.get_identifier_map()

        headers = {}
        if last_edited is not None:
            headers['Last-Modified'] = format_date_time(last_edited)

        response = api.make_response({'identifier_map': identifier_map},
                                     200, headers)

        return cache.long_time(response, server_only=True)


@add_resources('bags/<uuid:uuid>', endpoint='bag', suffixes=['json'])
class Bag(Resource):
    @auth.update_bag_permission.require()
    def put(self, uuid):

        try:
            data = parse_json(request)
        except ResourceError as e:
            return e.response()

        title = str(data.get('title', ''))
        if len(title) == 0:
            return {'message': 'A bag must have a title'}, 400

        items = data.get('items', [])
        if len(items) < 2:
            return {'message': 'A bag must have at least two items'}, 400

        try:
            defs, ctx = database.\
                        get_periods_and_context(items, raiseErrors=True)
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
        defs, defs_ctx = database.get_periods_and_context(data['items'])

        data['@id'] = identifier.prefix('bags/%s' % uuid)
        data['creator'] = bag['created_by']
        data['items'] = defs

        response = api.make_response(data, 200, headers)
        response.set_etag(bag_etag, weak=True)

        if version is None:
            return cache.no_time(response)
        else:
            return cache.long_time(response)


def external_graph_url(graph, version):
    if version is None:
        return url_for('graph', id=graph['id'], _external=True)
    return url_for('graph', id=graph['id'], version=version, _external=True)


def graph_container(url, graphs, version=None):
    return {
        '@context': {
            '@version': 1.1,
            'graphs': {
                '@id': url,
                '@container': ['@graph', '@id']
            }},
        'graphs': {
            external_graph_url(graph, version): json.loads(graph['data'])
            for graph in graphs
        }
    }


def get_graphs(prefix=None):
    if prefix and prefix.endswith('/'):
        prefix = prefix[:-1]
    url = (url_for('graphs', _external=True)
           + ((prefix + '/') if prefix else ''))
    return graph_container(url, database.get_graphs(prefix))


@add_resources('graphs', suffixes=['json'], barepaths=['/graphs/'], html=False)
class Graphs(Resource):
    def get(self):
        data = get_graphs()
        dataset = database.get_dataset()
        if dataset:
            dataset_url = url_for('dataset', _external=True)
            data['graphs'][dataset_url] = json.loads(dataset['data'])
        return cache.medium_time(
            api.make_response(data, 200, filename='periodo-graphs'))


@add_resources(
    'graphs/<path:id>',
    endpoint='graph',
    suffixes=['json'],
    html=False)
class Graph(Resource):
    @auth.update_graph_permission.require()
    def put(self, id):
        if id.endswith('/'):
            return {'message': 'graph uri path cannot end in /'}, 400
        try:
            version = database.create_or_update_graph(id, parse_json(request))
            if (version > 0):
                cache.purge_graph(id)
            return None, 201, {
                'Location': url_for('graph', id=id, version=version)
            }
        except ResourceError as e:
            return e.response()

    def get(self, id):
        data = get_graphs(prefix=id)
        filename = 'periodo-graph-{}'.format(id.replace('/', '-'))

        if len(data['graphs']) > 0:
            return cache.medium_time(
                api.make_response(data, 200, filename=filename))

        args = versioned_parser.parse_args()
        version = args.get('version')
        graph = database.get_graph(id, version=version)
        filename += ('' if version is None else '-v{}'.format(version))

        if not graph:
            abort(404)

        graph_etag = 'graph-{}-version-{}'.format(id, graph['version'])
        if request.if_none_match.contains_weak(graph_etag):
            return None, 304

        headers = {}
        headers['Last-Modified'] = format_date_time(graph['created_at'])

        data = graph_container(
            external_graph_url(graph, version), [graph], version)
        response = api.make_response(data, 200, headers, filename=filename)
        response.set_etag(graph_etag, weak=True)

        if version is None:
            return cache.medium_time(response)
        else:
            return cache.long_time(response)

    @auth.update_graph_permission.require()
    def delete(self, id):
        if database.delete_graph(id):
            cache.purge_graph(id)
            return None, 204
        else:
            abort(404)


@add_resources('identity', suffixes=['json'], barepaths=['/identity'])
class Identity(Resource):
    # submit_patch is the minimal permission
    @auth.submit_patch_permission.require()
    def get(self):
        if (g.identity.id is None):  # shouldn't be possible but just in case
            return {}, 200
        user = database.query_db(
            'SELECT name FROM user WHERE id = ?', (g.identity.id,), one=True)
        return {
            'id': g.identity.id,
            'name': user['name'],
            'permissions': auth.describe(g.identity.provides),
        }, 200
