import json
import re
from functools import reduce
from jsonpatch import JsonPatch, JsonPatchException
from jsonpointer import JsonPointerException
from periodo import database, void
from periodo.identifier import (
    replace_skolem_ids, IDENTIFIER_RE, IdentifierException)

CHANGE_PATH_PATTERN = re.compile(r'''
/authorities/
({id_pattern})   # match authority ID
(?:
  /periods/
  ({id_pattern}) # optionally match period ID
)?
'''.format(id_pattern=IDENTIFIER_RE.pattern[1:-1]), re.VERBOSE)


class InvalidPatchError(Exception):
    pass


class MergeError(Exception):
    def __init__(self, message):
        self.message = message


class UnmergeablePatchError(MergeError):
    pass


def from_text(patch_text):
    patch_text = patch_text or ''
    if isinstance(patch_text, bytes):
        patch_text = patch_text.decode()
    try:
        patch = json.loads(patch_text)
    except:  # noqa: E722
        raise InvalidPatchError('Patch data could not be parsed as JSON.')
    patch = JsonPatch(patch)
    return patch


def periods_of(authority, data):
    return set(data['authorities'][authority]['periods'].keys())


def analyze_change_path(path):
    match = CHANGE_PATH_PATTERN.match(path)
    return match.groups() if match else [None, None]


def analyze_change(change, data):
    o = {'updated': [], 'removed': []}
    [authority, period] = analyze_change_path(change['path'])
    if change['op'] == 'remove':
        if period:
            o['removed'] = [period]
            o['updated'] = [authority]
        elif authority:
            o['removed'] = set([authority]) | periods_of(authority, data)
    else:
        if period:
            o['updated'] = [period, authority]
        elif authority:
            o['updated'] = [authority]
    return o


def affected_entities(patch, data):
    def analyze(results, change):
        o = analyze_change(change, data)
        results['updated'] |= set(o['updated'])
        results['removed'] |= set(o['removed'])
        return results
    return reduce(analyze, patch, {'updated': set(), 'removed': set()})


def validate(patch, dataset):
    data = json.loads(dataset['data'])
    # Test to make sure it will apply
    try:
        patch.apply(data)
    except JsonPatchException:
        raise InvalidPatchError('Not a valid JSON patch.')
    except JsonPointerException:
        raise InvalidPatchError('Could not apply JSON patch to dataset.')

    return affected_entities(patch, data)


def create_request(patch, user_id):
    dataset = database.get_dataset()
    affected_entities = validate(patch, dataset)
    cursor = database.get_db().cursor()
    cursor.execute('''
INSERT INTO patch_request
(created_by, updated_by, created_from, updated_entities, removed_entities,
 original_patch)
VALUES (?, ?, ?, ?, ?, ?)
    ''', (user_id, user_id, dataset['id'],
          json.dumps(sorted(affected_entities['updated'])),
          json.dumps(sorted(affected_entities['removed'])),
          patch.to_string()))
    return cursor.lastrowid


def add_comment(patch_id, user_id, message):
    row = database.query_db(
        'SELECT * FROM patch_request WHERE id = ?', (patch_id,), one=True)

    if not row:
        raise MergeError('No patch with ID {}.'.format(patch_id))

    db = database.get_db()
    curs = db.cursor()
    curs.execute(
        '''
        INSERT INTO patch_request_comment
        (patch_request_id, author, message)
        VALUES (?, ?, ?)
        ''',
        (patch_id, user_id, message)
    )


def add_new_version_of_dataset(data):
    now = database.query_db(
        "SELECT CAST(strftime('%s', 'now') AS INTEGER) AS now", one=True
    )['now']
    cursor = database.get_db().cursor()
    cursor.execute(
        'INSERT into DATASET (data, description, created_at) VALUES (?,?,?)',
        (json.dumps(data), void.describe_dataset(data, now), now))
    return cursor.lastrowid


def reject(patch_id, user_id):
    row = database.query_db(
        'SELECT * FROM patch_request WHERE id = ?', (patch_id,), one=True)

    if not row:
        raise MergeError('No patch with ID {}.'.format(patch_id))
    if row['merged']:
        raise MergeError('Patch is already merged.')
    if not row['open']:
        raise MergeError('Closed patches cannot be merged.')

    db = database.get_db()
    curs = db.cursor()
    curs.execute(
        '''
        UPDATE patch_request
        SET merged = 0,
            open = 0,
            merged_at = strftime('%s', 'now'),
            merged_by = ?
        WHERE id = ?;
        ''',
        (user_id, row['id'],)
    )


def merge(patch_id, user_id):
    row = database.query_db(
        'SELECT * FROM patch_request WHERE id = ?', (patch_id,), one=True)

    if not row:
        raise MergeError('No patch with ID {}.'.format(patch_id))
    if row['merged']:
        raise MergeError('Patch is already merged.')
    if not row['open']:
        raise MergeError('Closed patches cannot be merged.')

    dataset = database.get_dataset()
    dataset_id_map = database.get_identifier_map()[0]
    mergeable = is_mergeable(row['original_patch'], dataset)

    if not mergeable:
        raise UnmergeablePatchError('Patch is not mergeable.')

    data = json.loads(dataset['data'])
    original_patch = from_text(row['original_patch'])
    try:
        applied_patch, patch_id_map = replace_skolem_ids(
            original_patch,
            data,
            database.get_removed_entity_keys(),
            dataset_id_map)
    except IdentifierException as e:
        raise UnmergeablePatchError(str(e))

    created_entities = set(patch_id_map.values())

    # Should this be ordered?
    new_data = applied_patch.apply(data)

    db = database.get_db()
    curs = db.cursor()
    curs.execute(
        '''
        UPDATE patch_request
        SET merged = 1,
            open = 0,
            merged_at = strftime('%s', 'now'),
            merged_by = ?,
            applied_to = ?,
            created_entities = ?,
            identifier_map = ?,
            applied_patch = ?
        WHERE id = ?;
        ''',
        (user_id,
         dataset['id'],
         json.dumps(sorted(created_entities)),
         json.dumps(patch_id_map),
         applied_patch.to_string(),
         row['id'])
    )
    version_id = add_new_version_of_dataset(new_data)
    curs.execute(
        '''
        UPDATE patch_request
        SET resulted_in = ?
        WHERE id = ?;
        ''',
        (version_id, row['id'])
    )


def is_mergeable(patch_text, dataset=None):
    dataset = dataset or database.get_dataset()
    patch = from_text(patch_text)
    mergeable = True
    try:
        patch.apply(json.loads(dataset['data']))
    except (JsonPatchException, JsonPointerException):
        mergeable = False
    return mergeable
