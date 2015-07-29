import json
import re
from functools import reduce
from jsonpatch import JsonPatch, JsonPatchException
from jsonpointer import JsonPointerException
from periodo import database, void
from periodo.identifier import replace_skolem_ids, IDENTIFIER_RE

CHANGE_PATH_PATTERN = re.compile(r'''
/periodCollections/
({id_pattern})   # match collection ID
(?:
  /definitions/
  ({id_pattern}) # optionally match definition ID
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
    except:
        raise InvalidPatchError('Patch data could not be parsed as JSON.')
    patch = JsonPatch(patch)
    return patch


def validate(patch, dataset):
    # Test to make sure it will apply
    try:
        patch.apply(json.loads(dataset['data']))
    except JsonPatchException:
        raise InvalidPatchError('Not a valid JSON patch.')
    except JsonPointerException:
        raise InvalidPatchError('Could not apply JSON patch to dataset.')

    matches = [CHANGE_PATH_PATTERN.match(change['path']) for change in patch]
    updated_entities = reduce(
        lambda s, groups: s | set(groups),
        [m.groups() for m in matches if m is not None], set())
    updated_entities.discard(None)
    return updated_entities


def create_request(patch, user_id):
    dataset = database.get_dataset()
    updated_entities = validate(patch, dataset)
    cursor = database.get_db().cursor()
    cursor.execute('''
INSERT INTO patch_request
(created_by, updated_by, created_from, updated_entities, original_patch)
VALUES (?, ?, ?, ?, ?)
    ''', (user_id, user_id, dataset['id'],
          json.dumps(sorted(updated_entities)), patch.to_string()))
    return cursor.lastrowid


def add_new_version_of_dataset(data):
    now = database.query_db(
        "SELECT CAST(strftime('%s', 'now') AS INTEGER) AS now", one=True)['now']
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
    mergeable = is_mergeable(row['original_patch'], dataset)

    if not mergeable:
        raise UnmergeablePatchError('Patch is not mergeable.')

    data = json.loads(dataset['data'])
    original_patch = from_text(row['original_patch'])
    applied_patch, id_map = replace_skolem_ids(original_patch, data)
    created_entities = set(id_map.values())

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
         json.dumps(id_map),
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
