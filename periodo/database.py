import json
import sqlite3
from periodo import app
from flask import g


def get_db():
    db = getattr(g, '_database', None)
    if db is None:
        db = g._database = sqlite3.connect(app.config['DATABASE'])
        db.row_factory = sqlite3.Row
    return db


def query_db(query, args=(), one=False):
    c = get_db().cursor()
    c.execute(query, args)
    rows = c.fetchall()
    c.close()
    return (rows[0] if rows else None) if one else rows


def get_dataset(version=None):
    if version is None:
        return query_db(
            'SELECT * FROM dataset ORDER BY id DESC', one=True)
    else:
        return query_db(
            'SELECT * FROM dataset WHERE dataset.id = ?', (version,), one=True)


def find_version_of_last_update(entity_id, version):
    cursor = get_db().cursor()
    for row in cursor.execute('''
    SELECT created_entities, updated_entities, resulted_in
    FROM patch_request
    WHERE merged = 1
    AND resulted_in <= ?
    ORDER BY id DESC''', (version,)).fetchall():
        if entity_id in json.loads(row['created_entities']):
            return row['resulted_in']
        if entity_id in json.loads(row['updated_entities']):
            return row['resulted_in']
    return None


def commit():
    get_db().commit()


@app.teardown_appcontext
def close(exception):
    db = getattr(g, '_database', None)
    if db is not None:
        db.close()
