import json
from rdflib import Graph, URIRef, Literal
from rdflib.collection import Collection
from rdflib.namespace import Namespace, XSD, FOAF
from periodo import database
from periodo.utils import isoformat, absolute_url

PROV = Namespace('http://www.w3.org/ns/prov#')


def timestamp(ts):
    return Literal(isoformat(ts), datatype=XSD.dateTime)


def history(app, inline_context=False):
    context = database.get_context()

    def uri(endpoint, **kwargs):
        return URIRef(absolute_url(app, context, endpoint, **kwargs))

    history_uri = uri('history')
    vocab_uri = uri('vocab')
    dataset_uri = uri('abstract_dataset')

    g = Graph()
    changelog = Collection(g, history_uri + '#changelog')

    for row in database.get_merged_patches():

        change = history_uri + '#change-{}'.format(row['id'])
        patch = history_uri + '#patch-{}'.format(row['id'])
        patch_uri = uri('patch', id=row['id'])
        version_in = uri('abstract_dataset', version=row['applied_to'])
        version_out = uri('abstract_dataset', version=row['resulted_in'])

        g.add((patch, FOAF.page, patch_uri))
        g.add((change, PROV.startedAtTime, timestamp(row['created_at'])))
        g.add((change, PROV.endedAtTime, timestamp(row['merged_at'])))

        g.add((version_in, PROV.specializationOf, dataset_uri))
        g.add((version_out, PROV.specializationOf, dataset_uri))

        g.add((change, PROV.used, version_in))
        g.add((change, PROV.used, patch))
        g.add((change, PROV.generated, version_out))

        for field, term in (('created_by', 'submitted'),
                            ('updated_by', 'updated'),
                            ('merged_by', 'merged')):

            if row[field] == 'initial-data-loader':
                continue

            agent = URIRef(row[field])
            assoc = history_uri + '#patch-{}-{}'.format(row['id'], term)

            g.add((change, PROV.wasAssociatedWith, agent))
            g.add((change, PROV.qualifiedAssociation, assoc))
            g.add((assoc, PROV.agent, agent))
            g.add((assoc, PROV.hadRole, vocab_uri + '#{}'.format(term)))

        changelog.append(change)

    def ordering(o):
        if o['id'].endswith('#changelog'):
            # sort first
            return ' '
        return o['id']

    jsonld = json.loads(
        g.serialize(format='json-ld', context=context).decode('utf-8')
    )
    jsonld['history'] = sorted(jsonld['history'], key=ordering)

    if inline_context:
        jsonld['@context']['__inline'] = True

    return jsonld
