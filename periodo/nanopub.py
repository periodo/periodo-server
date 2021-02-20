import json

from periodo import database, identifier


def as_uri(string):
    return {"@id": string}


def make_nanopub(period_id, version):
    result = database.query_db(
        '''
        SELECT
            patch.id as patch_id,

            patch.merged_at,
            patch.merged_by,
            patch.created_by,

            dataset.data
        FROM patch_request AS patch
        LEFT JOIN dataset ON patch.resulted_in = dataset.id
        WHERE
            patch.created_entities LIKE ?
            OR
            patch.updated_entities LIKE ?
        ORDER BY patch.id ASC
        LIMIT ?, 1;
        ''', (
            '%"' + identifier.prefix(period_id) + '"%',
            '%"' + identifier.prefix(period_id) + '"%',
            version - 1
        ), one=True)

    if not result:
        raise PeriodNotFoundError(
            'Could not find version {} of period {}'.format(
                version, period_id))

    data = json.loads(result['data'])

    authority_id = identifier.prefix(
        period_id[:identifier.AUTHORITY_SEQUENCE_LENGTH + 1])
    authority = data['authorities'][authority_id]
    source = authority['source']
    period = authority['periods'][identifier.prefix(period_id)]
    period['authority'] = authority_id

    nanopub_uri = '{}/nanopub{}'.format(
        identifier.prefix(period_id), version)
    patch_uri = identifier.prefix('h#change-{}'.format(result['patch_id']))

    context = data['@context'].copy()
    context['np'] = 'http://nanopub.org/nschema#'
    context['pub'] = data['@context']['@base'] + nanopub_uri + '#'
    context['prov'] = 'http://www.w3.org/ns/prov#'

    # TODO: Pop "source" from period and include it in the provenance
    # graph?

    return {
        "@context": context,
        "@graph": [
            {
                "@id": "pub:head",
                "@graph": {
                    "@id": nanopub_uri,
                    "@type": "np:Nanopublication",
                    "np:hasAssertion": as_uri("pub:assertion"),
                    "np:hasProvenance": as_uri("pub:provenance"),
                    "np:hasPublicationInfo": as_uri("pub:pubinfo"),
                }
            },
            {
                "@id": "pub:assertion",
                "@graph": [period]
            },
            {
                "@id": "pub:provenance",
                "@graph": [
                    {
                        "@id": 'pub:assertion',
                        "dc:source": source
                    }
                ]
            },
            {
                "@id": "pub:pubinfo",
                "@graph": [
                    {
                        "@id": nanopub_uri,
                        "prov:wasGeneratedBy": as_uri(patch_uri),
                        "prov:asGeneratedAtTime": result['merged_at'],
                        "prov:wasAttributedTo": [
                            as_uri(result['merged_by']),
                            as_uri(result['created_by'])
                        ]
                    }
                ]
            }
        ]
    }


class PeriodNotFoundError(Exception):
    pass
