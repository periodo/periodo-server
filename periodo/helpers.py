import datetime
import json
import os
import re
from flask import request, abort, redirect, url_for
from functools import reduce
from jsonpatch import JsonPatch, JsonPatchException
from jsonpointer import JsonPointerException
from periodo import database
from periodo.identifier import prefix, replace_skolem_ids, IDENTIFIER_RE
from rdflib import Graph, URIRef, Literal
from rdflib.namespace import Namespace, RDF, DCTERMS, XSD, VOID
from time import mktime

ISO_TIME_FMT = '%Y-%m-%d %H:%M:%S'

def iso_to_timestamp(iso_timestr, fmt=ISO_TIME_FMT):
    dt = datetime.datetime.strptime(iso_timestr, fmt)
    return mktime(dt.timetuple())


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
