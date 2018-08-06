import itertools
import json
import sqlite3
from periodo import app, identifier
from flask import g
from uuid import UUID


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
            'SELECT * FROM dataset ORDER BY id DESC LIMIT 1', one=True)
    else:
        return query_db(
            'SELECT * FROM dataset WHERE dataset.id = ?', (version,), one=True)


def get_context(version=None):
    return json.loads(get_dataset(version)['data']).get('@context')


def extract_authority(authority_key, o, raiseErrors=False):
    def maybeRaiseMissingKeyError():
        if raiseErrors:
            raise MissingKeyError(authority_key)

    if 'authorities' not in o:
        maybeRaiseMissingKeyError()
        return None

    if authority_key not in o['authorities']:
        maybeRaiseMissingKeyError()
        return None

    return o['authorities'][authority_key]


def extract_period(period_key, o, raiseErrors=False):
    def maybeRaiseMissingKeyError():
        if raiseErrors:
            raise MissingKeyError(period_key)

    authority_key = period_key[:7]
    authority = extract_authority(authority_key, o, raiseErrors)

    if period_key not in authority['periods']:
        maybeRaiseMissingKeyError()
        return None

    period = authority['periods'][period_key]
    period['authority'] = authority_key

    return period


def get_item(extract_item, id, version=None):
    dataset = get_dataset(version=version)
    o = json.loads(dataset['data'])
    item = extract_item(identifier.prefix(id), o, raiseErrors=True)
    item['@context'] = o['@context']
    if version is not None:
        item['@context']['__version'] = version

    return item


def get_authority(id, version=None):
    return get_item(extract_authority, id, version)


def get_period(id, version=None):
    return get_item(extract_period, id, version)


def get_periods_and_context(ids, version=None, raiseErrors=False):
    dataset = get_dataset(version=version)
    o = json.loads(dataset['data'])
    periods = {id: extract_period(id, o, raiseErrors) for id in ids}

    return periods, o['@context']


def get_patch_request_comments(patch_request_id):
    return query_db('''
SELECT id, author, message, posted_at
FROM patch_request_comment
WHERE patch_request_id=?
ORDER BY posted_at ASC''', (patch_request_id,))


def get_merged_patches():
    c = get_db().cursor()
    patches = c.execute('''
SELECT
  patch_request.id AS id,
  created_at,
  created_by,
  updated_by,
  merged_at,
  merged_by,
  applied_to,
  resulted_in,
  created_entities,
  updated_entities,
  removed_entities,
  COUNT(patch_request_comment.id) AS comment_count
FROM patch_request
LEFT OUTER JOIN patch_request_comment
ON patch_request_comment.patch_request_id = patch_request.id
WHERE merged = 1
GROUP BY patch_request.id
ORDER BY id ASC
''').fetchall()
    c.close()
    return patches


def get_bag_uuids():
    return [UUID(row['uuid']) for row in query_db('SELECT uuid FROM bag')]


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


def dump():
    return get_db().iterdump()


@app.teardown_appcontext
def close(exception):
    db = getattr(g, '_database', None)
    if db is not None:
        db.close()
