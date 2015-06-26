import json
from jsonpatch import JsonPatch
from periodo import app, database, patching


def init_db():
    with app.app_context():
        db = database.get_db()
        with app.open_resource('schema.sql', mode='r') as schema_file:
            db.cursor().executescript(schema_file.read())
        db.commit()


def load_data(datafile):
    with app.app_context():
        with open(datafile) as f:
            data = json.load(f)
        user_id = 'initial-data-loader'
        patch = JsonPatch.from_diff({}, data)
        patch_request_id = patching.create_request(patch, user_id)
        patching.merge(patch_request_id, user_id)
        database.commit()
