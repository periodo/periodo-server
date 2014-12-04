from collections import OrderedDict
import datetime
from email.utils import parsedate
import json
import sqlite3
from time import mktime
from wsgiref.handlers import format_date_time

from jsonpatch import JsonPatch, JsonPatchException
from jsonpointer import JsonPointerException

from flask import Flask, abort, g, request
from flask.ext.restful import (Api, Resource, fields, marshal, marshal_with,
                               reqparse)
from flask.ext.principal import Principal, Permission, ActionNeed

__all__ = ['init_db', 'load_data', 'app']


#########
# Setup #
#########

app = Flask(__name__)
app.config.update(
    DEBUG=True,
    DATABASE='./db.sqlite'
)

class PeriodOApi(Api):
    def unauthorized(self, response):
        response.headers['WWW-Authenticate'] = 'Bearer realm="PeriodO"'
        return response

api = PeriodOApi(app)

principals = Principal(app)

@app.after_request
def add_cors_headers(response):
    response.headers.add('Access-Control-Allow-Origin', '*')
    response.headers.add('Access-Control-Allow-Headers', 'If-Modified-Since')
    response.headers.add('Access-Control-Expose-Headers', 'Last-Modified')
    return response


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

submit_patch_permission = Permission(ActionNeed('submit-patch'))

#################
# API Resources #
#################

index_fields = {
    'dataset': fields.Url('dataset', absolute=True),
    'patches': fields.Url('patchlist', absolute=True)
}
class Index(Resource):
    @marshal_with(index_fields)
    def get(self):
        return {}

dataset_parser = reqparse.RequestParser()
dataset_parser.add_argument('If-Modified-Since', dest='modified', location='headers')
dataset_parser.add_argument('version', type=int, location='args',
                            help='Invalid version number')

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
    @submit_patch_permission.require(http_exception=401)
    def patch(self):
        try:
            dataset = self._get_latest_dataset()
            patch = patch_from_text(request.data)
            validate_patch(patch, dataset)
        except InvalidPatchException as e:
            return { 'status': 400, 'message': str(e) }, 400

        FIGURE_OUT_USERNAME = 'someone'
        username = FIGURE_OUT_USERNAME

        db = get_db()
        curs = db.cursor()
        curs.execute(
            'insert into patch_request (created_by, created_from) values (?, ?);',
            (username, dataset['id'])
        )
        patch_id = curs.lastrowid
        curs.execute(
            'insert into patch_text (created_by, patch_request, text) values(?, ?, ?);',
            (username, patch_id, patch.to_string())
        )
        db.commit()

        return None, 202, {
            'Location': api.url_for(PatchRequest, id=patch_id)
        }

PATCH_QUERY = """
select * 
from patch_request
left join (
    select
        id as current_text,
        max(created_at) as updated_at,
        created_by as updated_by,
        text,
        patch_request
    from patch_text
    group by patch_request
) as subq
on patch_request.id = subq.patch_request
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

class PatchRequest(Resource):
    def get(self, id):
        row = query_db(PATCH_QUERY + ' where id = ?', (id,), one=True)
        if not row:
            abort(404)
        data = process_patch_row(row)
        data['mergeable'] = is_mergeable(data['text'])
        return marshal(data, patch_fields)

class Patch(Resource):
    def get(self, id):
        row = query_db(PATCH_QUERY + ' where id = ?', (id,), one=True)
        return json.loads(row['text']), 200
    def put(self, id):
        try:
            patch = patch_from_text(request.data)
            validate_patch(patch)
        except InvalidPatchException as e:
            if str(e) != 'Could not apply JSON patch to dataset.':
                return { 'status': 400, 'message': str(e) }, 400

        db = get_db()
        curs = db.cursor()
        curs.execute(
            'insert into patch_text (created_by, patch_request, text) values(?, ?, ?);',
            ('SOMEONE', id, patch.to_string())
        )
        db.commit()

class PatchMerge(Resource):
    def post(self, id):
        row = query_db(PATCH_QUERY + ' where id = ?', (id,), one=True)

        if not row:
            abort(404)
        if row['merged']:
            return { 'message': 'Patch is already merged.' }, 404
        if not row['open']:
            return { 'message': 'Closed patches cannot be merged.' }, 404

        dataset = query_db('select * from dataset order by created desc', one=True)
        mergeable = is_mergeable(row['text'], dataset)

        if not mergeable:
            return { 'message': 'Patch is not mergeable.' }, 400

        patch = patch_from_text(row['text'])

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
                applied_to = ?
                resulted_in = ?
            where id = ?;
            ''',
            ('THE MERGER', dataset['id'], curs.lastrowid, row['id'])
        )
        db.commit()

        return None, 204


###############
# API Routing #
###############

api.add_resource(Index, '/')
api.add_resource(Dataset, '/dataset/')
api.add_resource(PatchList, '/patches/')
api.add_resource(PatchRequest, '/patches/<int:id>/')
api.add_resource(Patch, '/patches/<int:id>/patch.jsonpatch')
api.add_resource(PatchMerge, '/patches/<int:id>/merge')


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
