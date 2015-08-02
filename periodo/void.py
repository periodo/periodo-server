import json
import os
from datetime import datetime
from periodo import database
from rdflib import Graph, URIRef, Literal
from rdflib.namespace import Namespace, RDF, DCTERMS, XSD, VOID


def describe_dataset(data, created_at):
    cursor = database.get_db().cursor()
    contributors = cursor.execute('''
    SELECT DISTINCT created_by, updated_by
    FROM patch_request
    WHERE merged = 1
    AND id > 1''').fetchall()

    with open(os.path.join(os.path.dirname(__file__), 'void-stub.ttl')) as f:
        description_g = Graph().parse(file=f, format='turtle')
    ns = Namespace(description_g.value(
        predicate=RDF.type, object=VOID.DatasetDescription))
    dataset_g = Graph().parse(data=json.dumps(data), format='json-ld')

    partitions = description_g.objects(
        subject=ns.d, predicate=VOID.classPartition)
    for part in partitions:
        clazz = description_g.value(subject=part, predicate=VOID['class'])
        entity_count = len(dataset_g.query('''
        SELECT DISTINCT ?s
        WHERE {
          ?s a <%s> .
          FILTER (STRSTARTS(STR(?s), "%s"))
        }''' % (clazz, ns)))
        description_g.add(
            (part, VOID.entities, Literal(entity_count, datatype=XSD.integer)))

    linksets = description_g.subjects(predicate=RDF.type, object=VOID.Linkset)
    for linkset in linksets:
        target = description_g.value(
            subject=linkset, predicate=VOID.objectsTarget)
        predicate = description_g.value(
            subject=linkset, predicate=VOID.linkPredicate)
        uriSpace = description_g.value(
            subject=target, predicate=VOID.uriSpace).value
        triples = len(dataset_g.query('''
SELECT ?s ?p ?o
WHERE {
  ?s <%s> ?o .
  FILTER (STRSTARTS(STR(?o), "%s")) .
}''' % (predicate, uriSpace)))
        description_g.add(
            (linkset, VOID.triples, Literal(triples, datatype=XSD.integer)))

    def add_to_description(p, o):
        description_g.add((ns.d, p, o))

    add_to_description(
        DCTERMS.modified,
        Literal(datetime.utcfromtimestamp(created_at).isoformat(),
                datatype=XSD.dateTime))

    add_to_description(
        VOID.triples, Literal(len(dataset_g), datatype=XSD.integer))

    for row in contributors:
        add_to_description(
            DCTERMS.contributor, URIRef(row['created_by']))
        if row['updated_by']:
            add_to_description(
                DCTERMS.contributor, URIRef(row['updated_by']))

    return description_g.serialize(format='turtle')
