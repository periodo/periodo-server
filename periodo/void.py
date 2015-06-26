import json
import os
from periodo import database
from rdflib import Graph, URIRef, Literal
from rdflib.namespace import Namespace, RDF, DCTERMS, XSD, VOID


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
