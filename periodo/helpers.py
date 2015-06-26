import datetime
import json
import os
import re
from flask import request, abort, redirect, url_for
from functools import reduce
from jsonpatch import JsonPatch, JsonPatchException
from jsonpointer import JsonPointerException
from periodo import database, auth
from periodo.identifier import prefix, replace_skolem_ids, IDENTIFIER_RE
from rdflib import Graph, URIRef, Literal
from rdflib.namespace import Namespace, RDF, DCTERMS, XSD, VOID
from time import mktime

ISO_TIME_FMT = '%Y-%m-%d %H:%M:%S'

CHANGE_PATH_PATTERN = re.compile(r'''
/periodCollections/
({id_pattern})   # match collection ID
(?:
  /definitions/
  ({id_pattern}) # optionally match definition ID
)?
'''.format(id_pattern=IDENTIFIER_RE.pattern[1:-1]), re.VERBOSE)


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


def validate_patch(patch, dataset):
    # Test to make sure it will apply
    try:
        patch.apply(json.loads(dataset['data']))
    except JsonPatchException:
        raise InvalidPatchException('Not a valid JSON patch.')
    except JsonPointerException:
        raise InvalidPatchException('Could not apply JSON patch to dataset.')

    matches = [CHANGE_PATH_PATTERN.match(change['path']) for change in patch]
    affected_entities = reduce(
        lambda s, groups: s | set(groups),
        [m.groups() for m in matches if m is not None], set())
    affected_entities.discard(None)
    return affected_entities


def describe_dataset(data, created):
    cursor = database.get_db().cursor()
    contributors = cursor.execute('''
    SELECT DISTINCT created_by, updated_by
    FROM patch_request
    WHERE merged = 1
    AND id > 1''').fetchall()
    with open(os.path.join(os.path.dirname(__file__), 'void-stub.ttl')) as f:
        description = Graph().parse(file=f, format='turtle')
    ns = Namespace(description.value(
        predicate=RDF.type, object=VOID.DatasetDescription))
    dataset_g = Graph().parse(data=json.dumps(data), format='json-ld')

    for part in description[ns.d: VOID.classPartition]:
        clazz = description.value(subject=part, predicate=VOID['class'])
        entity_count = len(dataset_g.query('''
        SELECT DISTINCT ?s
        WHERE {
          ?s a <%s> .
          FILTER (STRSTARTS(STR(?s), "%s"))
        }''' % (clazz, ns)))
        description.add(
            (part, VOID.entities, Literal(entity_count, datatype=XSD.integer)))

    def add_to_description(p, o):
        description.add((ns.d, p, o))
    add_to_description(
        DCTERMS.modified, Literal(created, datatype=XSD.dateTime))
    add_to_description(
        VOID.triples, Literal(len(dataset_g), datatype=XSD.integer))
    for row in contributors:
        add_to_description(
            DCTERMS.contributor, URIRef(row['created_by']))
        if row['updated_by']:
            add_to_description(
                DCTERMS.contributor, URIRef(row['updated_by']))
    return description.serialize(format='turtle')


def add_new_version_of_dataset(data):
    now = database.query_db("SELECT CURRENT_TIMESTAMP AS now", one=True)['now']
    cursor = database.get_db().cursor()
    cursor.execute(
        'INSERT into DATASET (data, description, created) VALUES (?,?,?)',
        (json.dumps(data), describe_dataset(data, now), now))
    return cursor.lastrowid


def attach_to_dataset(o):
    o['primaryTopicOf'] = {'id': prefix(request.path[1:]),
                           'inDataset': prefix('d')}
    return o


def create_patch_request(patch, user_id):
    dataset = database.get_dataset()
    affected_entities = validate_patch(patch, dataset)
    cursor = database.get_db().cursor()
    cursor.execute('''
INSERT INTO patch_request
(created_by, updated_by, created_from, affected_entities, original_patch)
VALUES (?, ?, ?, ?, ?)
    ''', (user_id, user_id, dataset['id'],
          json.dumps(sorted(affected_entities)), patch.to_string()))
    return cursor.lastrowid


def find_version_of_last_update(entity_id, version):
    cursor = database.get_db().cursor()
    for row in cursor.execute('''
    SELECT affected_entities, resulted_in
    FROM patch_request
    WHERE merged = 1
    AND resulted_in <= ?
    ORDER BY id DESC''', (version,)).fetchall():
        if prefix(entity_id) in json.loads(row['affected_entities']):
            return row['resulted_in']
    return None


def redirect_to_last_update(entity_id, version):
    if version is None:
        return None
    v = find_version_of_last_update(entity_id, version)
    if v is None:
        abort(404)
    if v == int(version):
        return None
    return redirect(request.path + '?version={}'.format(v), code=301)


class MergeError(Exception):
    def __init__(self, message):
        self.message = message


class UnmergeablePatchError(MergeError):
    pass


def merge_patch(patch_id, user_id):
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
    original_patch = patch_from_text(row['original_patch'])
    applied_patch, new_ids = replace_skolem_ids(original_patch, data)
    affected_entities = (set(json.loads(row['affected_entities']))
                         | set(new_ids))

    # Should this be ordered?
    new_data = applied_patch.apply(data)

    db = database.get_db()
    curs = db.cursor()
    curs.execute(
        '''
        UPDATE patch_request
        SET merged = 1,
            open = 0,
            merged_at = CURRENT_TIMESTAMP,
            merged_by = ?,
            applied_to = ?,
            affected_entities = ?,
            applied_patch = ?
        WHERE id = ?;
        ''',
        (user_id,
         dataset['id'],
         json.dumps(sorted(affected_entities)),
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
    patch = patch_from_text(patch_text)
    mergeable = True
    try:
        patch.apply(json.loads(dataset['data']))
    except (JsonPatchException, JsonPointerException):
        mergeable = False
    return mergeable


def make_dataset_url(version):
    return url_for('dataset', _external=True) + '?version=' + str(version)


def process_patch_row(row):
    d = dict(row)
    d['created_from'] = make_dataset_url(row['created_from'])
    d['applied_to'] = make_dataset_url(
        row['created_from']) if row['applied_to'] else None
    return d
