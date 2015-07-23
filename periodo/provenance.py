import json
from datetime import datetime
from flask import url_for
from rdflib import Graph, URIRef, Literal
from rdflib.collection import Collection
from rdflib.namespace import Namespace, XSD, FOAF
from periodo import database, identifier

PROV = Namespace('http://www.w3.org/ns/prov#')
PERIODO = Namespace('http://n2t.net/ark:/99152/')

CONTEXT = {
    "@base": "http://n2t.net/ark:/99152/p0h",
    "by": {"@id": "prov:wasAssociatedWith", "@type": "@id"},
    "foaf": "http://xmlns.com/foaf/0.1/",
    "generated": {"@id": "prov:generated", "@type": "@id"},
    "history": "@graph",
    "id": "@id",
    "initialDataLoad": {"@id": "rdf:first", "@type": "@id"},
    "mergedAt": {"@id": "prov:endedAtTime", "@type": "xsd:dateTime"},
    "mergedPatches": {"@id": "rdf:rest"},
    "name": "foaf:name",
    "prov": "http://www.w3.org/ns/prov#",
    "rdf": "http://www.w3.org/1999/02/22-rdf-syntax-ns#",
    "role": {"@id": "prov:hadRole", "@type": "@id"},
    "roles": {"@id": "prov:qualifiedAssociation", "@type": "@id"},
    "specializationOf": {"@id": "prov:specializationOf", "@type": "@id"},
    "submittedAt": {"@id": "prov:startedAtTime", "@type": "xsd:dateTime"},
    "type": "@type",
    "url": {"@id": "foaf:page", "@type": "@id"},
    "used": {"@id": "prov:used", "@type": "@id"},
    "wasRevisionOf": {"@id": "prov:wasRevisionOf", "@type": "@id"},
    "xsd": "http://www.w3.org/2001/XMLSchema#"
}


def history():
    g = Graph()
    changelog = Collection(g, URIRef('#changelog'))
    cursor = database.get_db().cursor()
    for row in cursor.execute('''
SELECT
  id,
  created_at,
  created_by,
  updated_by,
  merged_at,
  merged_by,
  applied_to,
  resulted_in,
  affected_entities
FROM patch_request
WHERE merged = 1
ORDER BY id ASC
''').fetchall():
        change = URIRef('#change-{}'.format(row['id']))
        patch = URIRef('#patch-{}'.format(row['id']))
        g.add((patch,
               FOAF.page,
               PERIODO[identifier.prefix(url_for('patch', id=row['id']))]))
        g.add((change,
               PROV.startedAtTime,
               Literal(datetime.utcfromtimestamp(row['created_at']).isoformat(),
                       datatype=XSD.dateTime)))
        g.add((change,
               PROV.endedAtTime,
               Literal(datetime.utcfromtimestamp(row['merged_at']).isoformat(),
                       datatype=XSD.dateTime)))
        dataset = PERIODO[identifier.prefix(url_for('abstract_dataset'))]
        version_in = PERIODO[identifier.prefix(
            url_for('abstract_dataset', version=row['applied_to']))]
        g.add((version_in, PROV.specializationOf, dataset))
        version_out = PERIODO[identifier.prefix(
            url_for('abstract_dataset', version=row['resulted_in']))]
        g.add((version_out, PROV.specializationOf, dataset))

        g.add((change, PROV.used, version_in))
        g.add((change, PROV.used, patch))
        g.add((change, PROV.generated, version_out))

        for entity_id in json.loads(row['affected_entities']):
            entity = PERIODO[entity_id]
            entity_version = PERIODO[
                entity_id + '?version={}'.format(row['resulted_in'])]
            prev_entity_version = PERIODO[
                entity_id + '?version={}'.format(row['applied_to'])]
            g.add(
                (entity_version, PROV.specializationOf, entity))
            g.add(
                (entity_version, PROV.wasRevisionOf, prev_entity_version))
            g.add((change, PROV.generated, entity_version))

        for field, term in (('created_by', 'submitted'),
                            ('updated_by', 'updated'),
                            ('merged_by', 'merged')):
            if row[field] == 'initial-data-loader':
                continue
            agent = URIRef(row[field])
            association = URIRef('#patch-{}-{}'.format(row['id'], term))
            g.add((change, PROV.wasAssociatedWith, agent))
            g.add((change, PROV.qualifiedAssociation, association))
            g.add((association, PROV.agent, agent))
            g.add((association,
                   PROV.hadRole,
                   PERIODO[identifier.prefix(url_for('vocab') + '#' + term)]))

        changelog.append(change)

    return g.serialize(format='json-ld', context=CONTEXT).decode('utf-8')
