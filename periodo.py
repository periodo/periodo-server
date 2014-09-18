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

__all__ = ['init_db', 'app']

DATABASE = './db.sqlite'


#########
# Setup #
#########

app = Flask(__name__)
app.config.update(
    DEBUG=True
)

api = Api(app)

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

def process_patch_row(row):
    d = dict(row)
    d['created_from'] = make_dataset_url(row['created_from'])
    d['applied_to'] = make_dataset_url(row['created_from']) if row['applied_to'] else None
    return d

class PatchList(Resource):
    def get(self):
        query = PATCH_QUERY
        rows = query_db(PATCH_QUERY)
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
        data['mergeable'] = True

        dataset = query_db('select * from dataset order by created desc', one=True)
        patch = patch_from_text(data['text'])
        try:
            patch.apply(json.loads(dataset['data']))
        except JsonPatchException:
            data['mergeable'] = False
        except JsonPointerException:
            data['mergeable'] = False

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


###############
# API Routing #
###############

api.add_resource(Index, '/')
api.add_resource(Dataset, '/dataset/')
api.add_resource(PatchList, '/patches/')
api.add_resource(PatchRequest, '/patches/<int:id>/')
api.add_resource(Patch, '/patches/<int:id>/patch.jsonpatch')


######################
#  Database handling #
######################

def init_db():
    with app.app_context():
        db = get_db()
        with app.open_resource('schema.sql', mode='r') as schema_file:
            db.cursor().executescript(schema_file.read())
        db.commit()

def get_db():
    db = getattr(g, '_database', None)
    if db is None:
        db = g._database = sqlite3.connect(DATABASE)
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
