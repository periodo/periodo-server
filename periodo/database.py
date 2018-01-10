import itertools
import json
import sqlite3
from periodo import app, identifier
from flask import g


class MissingKeyError(Exception):
    def __init__(self, key):
        self.key = key


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


def extract_collection(collection_key, o, raiseErrors=False):
    def maybeRaiseMissingKeyError():
        if raiseErrors:
            raise MissingKeyError(collection_key)

    if 'periodCollections' not in o:
        maybeRaiseMissingKeyError()
        return None

    if collection_key not in o['periodCollections']:
        maybeRaiseMissingKeyError()
        return None

    return o['periodCollections'][collection_key]


def extract_definition(definition_key, o, raiseErrors=False):
    def maybeRaiseMissingKeyError():
        if raiseErrors:
            raise MissingKeyError(definition_key)

    collection_key = definition_key[:7]
    collection = extract_collection(collection_key, o, raiseErrors)

    if definition_key not in collection['definitions']:
        maybeRaiseMissingKeyError()
        return None

    definition = collection['definitions'][definition_key]
    definition['collection'] = collection_key

    return definition


def get_item(extract_item, id, version=None):
    dataset = get_dataset(version=version)
    o = json.loads(dataset['data'])
    item = extract_item(identifier.prefix(id), o, raiseErrors=True)
    item['@context'] = o['@context']
    if version is not None:
        item['@context']['__version'] = version

    return item


def get_collection(id, version=None):
    return get_item(extract_collection, id, version)


def get_definition(id, version=None):
    return get_item(extract_definition, id, version)


def get_definitions_and_context(ids, version=None, raiseErrors=False):
    dataset = get_dataset(version=version)
    o = json.loads(dataset['data'])
    definitions = {id: extract_definition(id, o, raiseErrors) for id in ids}

    return definitions, o['@context']


def get_bag_ids():
    return query_db('SELECT uuid FROM bag')


def get_bag(uuid, version=None):
    if version is None:
        return query_db(
            'SELECT * FROM bag WHERE uuid = ? ORDER BY version DESC LIMIT 1',
            (uuid.hex,), one=True)
    else:
        return query_db(
            'SELECT * FROM bag WHERE uuid = ? AND version = ?',
            (uuid.hex, version), one=True)


def create_or_update_bag(uuid, creator_id, data):
    db = get_db()
    c = get_db().cursor()
    c.execute('''
    SELECT MAX(version) AS max_version
    FROM bag
    WHERE uuid = ?''', (uuid.hex,))
    row = c.fetchone()
    version = 0 if row['max_version'] is None else row['max_version'] + 1
    if version > 0:
        data['wasRevisionOf'] = identifier.prefix('bags/{}?version={}'.format(
            uuid, row['max_version']))
    c.execute('''
    INSERT INTO bag (
               uuid,
               version,
               created_by,
               data,
               owners)
    VALUES (?, ?, ?, ?, ?)''',
              (uuid.hex,
               version,
               creator_id,
               json.dumps(data),
               json.dumps([creator_id])))
    c.close()
    db.commit()
    return version


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


def get_removed_entity_keys():
    return set(itertools.chain(
        *[json.loads(row['removed_entities']) for row in query_db('''
SELECT removed_entities FROM patch_request WHERE merged = 1''')]))


def commit():
    get_db().commit()


@app.teardown_appcontext
def close(exception):
    db = getattr(g, '_database', None)
    if db is not None:
        db.close()
