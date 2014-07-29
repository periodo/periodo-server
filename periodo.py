import datetime
import json
import sqlite3
from time import mktime
from wsgiref.handlers import format_date_time

from flask import Flask, abort, g
from flask.ext.restful import Api, Resource, fields, marshal_with, reqparse

__all__ = ['init_db']

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
    response.headers.add('Access-Control-Allow-Headers', 'If-None-Match')
    response.headers.add('Access-Control-Expose-Headers', 'ETag')
    return response


###############
# API Helpers #
###############

def iso_to_http_time(iso_timestr, fmt='%Y-%m-%d %H:%M:%S'):
    dt = datetime.datetime.strptime(iso_timestr, fmt)
    stamp = mktime(dt.timetuple())
    return format_date_time(stamp)

dataset_parser = reqparse.RequestParser()
dataset_parser.add_argument('If-None-Match', dest='etag_match',
                            location='headers', type=int)


#################
# API Resources #
#################

index_fields = {
    'dataset': fields.Url('dataset', absolute=True)
}
class Index(Resource):
    @marshal_with(index_fields)
    def get(self):
        return {}

class Dataset(Resource):
    def get(self):
        args = dataset_parser.parse_args()
        dataset = query_db('select * from dataset order by created desc', one=True)

        if not dataset:
            abort(501)

        if args['etag_match'] and args['etag_match'] == dataset['id']:
            return None, 304

        return json.loads(dataset['data']), 200, {
            'Last-Modified': iso_to_http_time(dataset['created']),
            'ETag': dataset['id']
        }

###############
# API Routing #
###############

api.add_resource(Index, '/', endpoint='index')
api.add_resource(Dataset, '/dataset/', endpoint='dataset')


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
