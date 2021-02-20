import os
from collections import defaultdict
from periodo import database, utils
from rdflib import Graph, URIRef, Literal
from rdflib.namespace import Namespace, RDF, DCTERMS, XSD, VOID

SKOS = Namespace('http://www.w3.org/2004/02/skos/core#')
OWL = Namespace('http://www.w3.org/2002/07/owl#')

SOURCE_URISPACES = [
    'http://www.worldcat.org/oclc/',
    'http://dx.doi.org/',
]

SAMEAS_URISPACES = [
    'http://purl.org/heritagedata/schemes/eh_period',
    'http://pleiades.stoa.org/vocabularies/time-periods/',
]


def count_entities(data, clazz):
    count = 0
    if clazz == SKOS.Concept:
        for authority in data['authorities'].values():
            for period in authority['periods'].values():
                count += 1
    elif clazz == SKOS.ConceptScheme:
        for authority in data['authorities'].values():
            count += 1
    return count


def id(d):
    return d.get('id', d.get('@id', ''))


def resolve(predicate, source):
    x = source.get(predicate, '')
    if isinstance(x, str):
        return x
    else:
        return id(x)


def count_source_links(source, counts):
    source_id = id(source)
    source_partOf = resolve('partOf', source)
    for u in SOURCE_URISPACES:
        if source_id.startswith(u):
            counts[u][DCTERMS.source] += 1
        if source_partOf.startswith(u):
            counts[u][DCTERMS.isPartOf] += 1


def get_linkset_counts(data):
    counts = defaultdict(lambda: defaultdict(int))
    for authority in data['authorities'].values():
        source = authority.get('source', {})
        count_source_links(source, counts)

        for period in authority['periods'].values():
            source = period.get('source', {})
            count_source_links(source, counts)

            period_sameAs = period.get('sameAs', '')
            for u in SAMEAS_URISPACES:
                if period_sameAs.startswith(u):
                    counts[u][OWL.sameAs] += 1

            u = 'http://www.wikidata.org/entity/'
            for place in period.get('spatialCoverage', []):
                if id(place).startswith(u):
                    counts[u][DCTERMS.spatial] += 1
    return counts


def describe_dataset(data, created_at):
    contributors = database.query_db('''
    SELECT DISTINCT created_by, updated_by
    FROM patch_request
    WHERE merged = 1
    AND id > 1
    ''')

    with open(os.path.join(os.path.dirname(__file__), 'void-stub.ttl')) as f:
        description_g = Graph().parse(file=f, format='turtle')
    ns = Namespace(description_g.value(
        predicate=RDF.type, object=VOID.DatasetDescription))

    partitions = description_g.objects(
        subject=ns.d, predicate=VOID.classPartition)
    for part in partitions:
        clazz = description_g.value(
            subject=part,
            predicate=VOID['class']
        )
        entity_count = count_entities(data, clazz)
        description_g.add(
            (part, VOID.entities, Literal(entity_count, datatype=XSD.integer)))

    linksets = description_g.subjects(predicate=RDF.type, object=VOID.Linkset)
    counts = get_linkset_counts(data)
    for linkset in linksets:
        target = description_g.value(
            subject=linkset, predicate=VOID.objectsTarget)
        uriSpace = str(description_g.value(
            subject=target, predicate=VOID.uriSpace).value)
        predicate = description_g.value(
            subject=linkset, predicate=VOID.linkPredicate)
        triples = counts[uriSpace][predicate]
        description_g.add(
            (linkset, VOID.triples, Literal(triples, datatype=XSD.integer)))

    def add_to_description(p, o):
        description_g.add((ns.d, p, o))

    add_to_description(
        DCTERMS.modified,
        Literal(utils.isoformat(created_at), datatype=XSD.dateTime))

    add_to_description(
        DCTERMS.provenance,
        URIRef(utils.absolute_url(data['@context']['@base'], 'history')
               + '#changes')
    )

    for row in contributors:
        add_to_description(
            DCTERMS.contributor, URIRef(row['created_by']))
        if row['updated_by']:
            add_to_description(
                DCTERMS.contributor, URIRef(row['updated_by']))

    return description_g.serialize(format='turtle')
