import json
from rdflib import Graph, URIRef, Literal
from rdflib.collection import Collection
from rdflib.namespace import Namespace, XSD, FOAF, DCTERMS, RDF, RDFS
from periodo import database, identifier
from periodo.utils import isoformat, absolute_url

PROV = Namespace("http://www.w3.org/ns/prov#")
AS = Namespace("https://www.w3.org/ns/activitystreams#")


def timestamp(ts):
    return Literal(isoformat(ts), datatype=XSD.dateTime)


def count(n):
    return Literal(n, datatype=XSD.nonNegativeInteger)


def is_period_id(entity_id):
    return len(entity_id) == (
        0
        + identifier.AUTHORITY_SEQUENCE_LENGTH
        + 1
        + identifier.PERIOD_SEQUENCE_LENGTH
        + 1
    )


def is_authority_id(entity_id):
    return len(entity_id) == identifier.AUTHORITY_SEQUENCE_LENGTH + 1


def entity_uri(uri_for, entity_id, **kwargs):
    unprefixed_id = identifier.unprefix(entity_id)

    if is_period_id(unprefixed_id):
        return uri_for("period", period_id=unprefixed_id, **kwargs)

    if is_authority_id(unprefixed_id):
        return uri_for("authority", authority_id=unprefixed_id, **kwargs)

    return entity_id


def add_entity_details(g, row, change, uri_for):
    def add_entity_version(entity_id):
        entity = entity_uri(uri_for, entity_id)
        entity_ver = entity_uri(uri_for, entity_id, version=row["resulted_in"])
        g.add((entity_ver, PROV.specializationOf, entity))
        g.add((change, PROV.generated, entity_ver))
        return entity_ver

    for entity_id in json.loads(row["created_entities"]):
        add_entity_version(entity_id)

    for entity_id in json.loads(row["updated_entities"]):
        entity_ver = add_entity_version(entity_id)
        prev_ver = entity_uri(uri_for, entity_id, version=row["applied_to"])
        g.add((entity_ver, PROV.wasRevisionOf, prev_ver))

    for entity_id in json.loads(row["removed_entities"]):
        g.add((change, PROV.invalidated, entity_uri(uri_for, entity_id)))


def history(include_entity_details=False):
    base = database.get_context()["@base"]

    def uri_for(endpoint, **kwargs):
        return URIRef(absolute_url(base, endpoint, **kwargs))

    history_uri = uri_for("history")
    vocab_uri = uri_for("vocabulary")
    dataset_uri = uri_for("abstract_dataset")
    changes_uri = history_uri + "#changes"

    g = Graph()
    changes = Collection(g, changes_uri)

    for row in database.get_merged_patches():

        change = history_uri + "#change-{}".format(row["id"])
        patch = history_uri + "#patch-{}".format(row["id"])
        patch_uri = uri_for("patch", id=row["id"])
        patchrequest = history_uri + "#patch-request-{}".format(row["id"])
        patchrequest_uri = uri_for("patchrequest", id=row["id"])
        comments = history_uri + "#patch-request-{}-comments".format(row["id"])
        version_in = uri_for("abstract_dataset", version=row["applied_to"])
        version_out = uri_for("abstract_dataset", version=row["resulted_in"])

        g.add((patch, FOAF.page, patch_uri))
        g.add((patchrequest, FOAF.page, patchrequest_uri))

        g.add((change, PROV.startedAtTime, timestamp(row["created_at"])))
        g.add((change, PROV.endedAtTime, timestamp(row["merged_at"])))

        g.add((version_in, PROV.specializationOf, dataset_uri))
        g.add((version_out, PROV.specializationOf, dataset_uri))

        g.add((change, PROV.used, version_in))
        g.add((change, PROV.used, patch))
        g.add((change, PROV.generated, version_out))

        g.add((change, RDFS.seeAlso, patchrequest))

        if include_entity_details:
            add_entity_details(g, row, change, uri_for)

        if row["comment_count"] > 0:
            g.add((patchrequest, AS.replies, comments))
            g.add((comments, AS.totalItems, count(row["comment_count"])))

            for i, subrow in enumerate(database.get_patch_request_comments(row["id"])):

                comment = history_uri + "#patch-request-{}-comment-{}".format(
                    row["id"], subrow["id"]
                )
                g.add((comments, AS.items, comment))
                if i == 0:
                    g.add((comments, AS.first, comment))
                if i == (row["comment_count"] - 1):
                    g.add((comments, AS.last, comment))
                g.add((comment, RDF.type, AS.Note))
                g.add((comment, AS.attributedTo, URIRef(subrow["author"])))
                g.add((comment, AS.published, timestamp(subrow["posted_at"])))
                g.add((comment, AS.mediaType, Literal("text/plain")))
                g.add((comment, AS.content, Literal(subrow["message"])))

        for field, term in (
            ("created_by", "submitted"),
            ("updated_by", "updated"),
            ("merged_by", "merged"),
        ):

            if row[field] == "initial-data-loader":
                continue

            agent = URIRef(row[field])
            assoc = history_uri + "#patch-{}-{}".format(row["id"], term)

            g.add((change, PROV.wasAssociatedWith, agent))
            g.add((change, PROV.qualifiedAssociation, assoc))
            g.add((assoc, PROV.agent, agent))
            g.add((assoc, PROV.hadRole, vocab_uri + "#{}".format(term)))

        changes.append(change)

    g.add((dataset_uri, DCTERMS.provenance, changes_uri))

    return g
