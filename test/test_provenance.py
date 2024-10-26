import httpx
import pytest
import re
from rdflib import Dataset, Literal, URIRef
from rdflib.namespace import Namespace, RDFS, FOAF, RDF
from urllib.parse import urlparse
from periodo import DEV_SERVER_NAME
from typing import cast

PERIODO = Namespace("http://n2t.net/ark:/99152/")
PROV = Namespace("http://www.w3.org/ns/prov#")
AS = Namespace("https://www.w3.org/ns/activitystreams#")
HOST = Namespace(f"http://{DEV_SERVER_NAME}/")

W3CDTF = r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}\+00.00$"


@pytest.mark.client_auth_token("this-token-has-normal-permissions")
def test_get_history(
    active_user,
    admin_user,
    client,
    bearer_auth,
    load_json,
):
    res = client.patch(
        "/d/",
        json=load_json("test-patch-adds-items.json"),
    )
    patch_url = urlparse(res.headers["Location"]).path
    client.post(patch_url + "messages", json={"message": "Here is my patch"})
    client.post(
        patch_url + "messages",
        json={"message": "Looks good to me"},
        auth=bearer_auth("this-token-has-admin-permissions"),
    )
    client.post(
        patch_url + "merge", auth=bearer_auth("this-token-has-admin-permissions")
    )

    def check_redirects_to_nt(content_type):
        res = client.get("/h", headers={"Accept": content_type})
        assert res.status_code == httpx.codes.SEE_OTHER
        assert urlparse(res.headers["Location"]).path == "/h.nt"

    check_redirects_to_nt("text/turtle")
    check_redirects_to_nt("application/ld+json")
    check_redirects_to_nt("application/n-triples")

    res = client.get("/history.nt?full")
    assert res.status_code == httpx.codes.OK
    assert res.headers["Content-Type"] == "application/n-triples"

    g = Dataset()
    g.parse(format="nt", data=res.text)

    # Initial data load
    assert (HOST["h#change-1"], PROV.endedAtTime, None) in g
    assert (HOST["h#change-1"], PROV.used, HOST["d?version=0"]) in g
    assert (HOST["d?version=0"], PROV.specializationOf, HOST["d"]) in g
    assert (HOST["h#change-1"], RDFS.seeAlso, HOST["h#patch-request-1"]) in g
    assert (HOST["h#patch-request-1"], FOAF.page, HOST["patches/1/"]) in g
    assert (
        HOST["h#patch-request-1"],
        AS.replies,
        HOST["h#patch-request-1-comments"],
    ) not in g
    assert (HOST["h#change-1"], PROV.used, HOST["h#patch-1"]) in g
    assert (HOST["h#patch-1"], FOAF.page, HOST["patches/1/patch.jsonpatch"]) in g
    assert (HOST["h#change-1"], PROV.generated, HOST["d?version=1"]) in g
    assert (HOST["d?version=1"], PROV.specializationOf, HOST["d"]) in g
    assert (HOST["h#change-1"], PROV.generated, HOST["trgkv?version=1"]) in g
    assert (HOST["trgkv?version=1"], PROV.specializationOf, HOST["trgkv"]) in g
    assert (HOST["h#change-1"], PROV.generated, HOST["trgkvwbjd?version=1"]) in g
    assert (HOST["trgkvwbjd?version=1"], PROV.specializationOf, HOST["trgkvwbjd"]) in g

    # Change from first submitted patch
    assert (HOST["h#change-2"], PROV.startedAtTime, None) in g
    assert (HOST["h#change-2"], PROV.endedAtTime, None) in g

    def check_time(time):
        assert time.datatype == URIRef("http://www.w3.org/2001/XMLSchema#dateTime")
        assert re.match(W3CDTF, time.value.isoformat())

    check_time(g.value(subject=HOST["h#change-2"], predicate=PROV.startedAtTime))
    check_time(g.value(subject=HOST["h#change-2"], predicate=PROV.endedAtTime))

    assert (
        HOST["h#change-2"],
        PROV.wasAssociatedWith,
        URIRef("https://orcid.org/1234-5678-9101-112X"),
    ) in g
    assert (
        HOST["h#change-2"],
        PROV.wasAssociatedWith,
        URIRef("https://orcid.org/1211-1098-7654-321X"),
    ) in g

    for association in g.subjects(
        predicate=PROV.agent, object=URIRef("https://orcid.org/1234-5678-9101-112X")
    ):
        role = g.value(subject=association, predicate=PROV.hadRole)
        assert role in (HOST["v#submitted"], HOST["v#updated"])

    merger = g.value(
        predicate=PROV.agent, object=URIRef("https://orcid.org/1211-1098-7654-321X")
    )
    assert (HOST["h#change-2"], PROV.qualifiedAssociation, merger) in g
    assert (merger, PROV.hadRole, HOST["v#merged"]) in g
    assert (HOST["h#change-2"], PROV.used, HOST["d?version=1"]) in g
    assert (HOST["d?version=1"], PROV.specializationOf, HOST["d"]) in g
    assert (HOST["h#change-2"], RDFS.seeAlso, HOST["h#patch-request-2"]) in g
    assert (HOST["h#patch-request-2"], FOAF.page, HOST["patches/2/"]) in g
    assert (
        HOST["h#patch-request-2"],
        AS.replies,
        HOST["h#patch-request-2-comments"],
    ) in g
    commentCount = g.value(
        subject=HOST["h#patch-request-2-comments"], predicate=AS.totalItems
    )
    assert commentCount is not None
    assert cast(Literal, commentCount).value == 2
    assert (
        HOST["h#patch-request-2-comments"],
        AS.first,
        HOST["h#patch-request-2-comment-1"],
    ) in g
    assert (
        HOST["h#patch-request-2-comments"],
        AS.last,
        HOST["h#patch-request-2-comment-2"],
    ) in g

    def check_comment(num, commenter, comment):
        assert (
            HOST["h#patch-request-2-comments"],
            AS.items,
            HOST[f"h#patch-request-2-comment-{num}"],
        ) in g
        assert (HOST[f"h#patch-request-2-comment-{num}"], RDF.type, AS.Note) in g
        assert (HOST[f"h#patch-request-2-comment-{num}"], AS.published, None) in g
        assert (
            cast(
                Literal,
                g.value(
                    subject=HOST[f"h#patch-request-2-comment-{num}"],
                    predicate=AS.mediaType,
                ),
            ).value
            == "text/plain"
        )
        assert (
            HOST[f"h#patch-request-2-comment-{num}"],
            AS.attributedTo,
            URIRef(commenter),
        ) in g
        assert (
            cast(
                Literal,
                g.value(
                    subject=HOST[f"h#patch-request-2-comment-{num}"],
                    predicate=AS.content,
                ),
            ).value
            == comment
        )

    check_comment(1, "https://orcid.org/1234-5678-9101-112X", "Here is my patch")
    check_comment(2, "https://orcid.org/1211-1098-7654-321X", "Looks good to me")

    assert (HOST["h#change-2"], PROV.used, HOST["h#patch-2"]) in g
    assert (HOST["h#patch-2"], FOAF.page, HOST["patches/2/patch.jsonpatch"]) in g
    assert (HOST["h#change-2"], PROV.generated, HOST["d?version=2"]) in g
    assert (HOST["d?version=2"], PROV.specializationOf, HOST["d"]) in g
    assert (HOST["h#change-2"], PROV.generated, HOST["trgkv?version=2"]) in g
    assert (HOST["trgkv?version=2"], PROV.specializationOf, HOST["trgkv"]) in g
    assert (HOST["trgkv?version=2"], PROV.wasRevisionOf, HOST["trgkv?version=1"]) in g

    entity_count = 0
    for _, _, version in g.triples((HOST["h#change-2"], PROV.generated, None)):
        entity = g.value(subject=version, predicate=PROV.specializationOf)
        assert f"{entity}?version=2" == str(version)
        entity_count += 1
    assert entity_count == 6
