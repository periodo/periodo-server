import httpx
import json
import csv
from rdflib import Graph, URIRef
from rdflib.plugins import sparql
from rdflib.namespace import Namespace, DCTERMS, RDF
from urllib.parse import urlparse, urlencode
from periodo import DEV_SERVER_NAME, cache

VOID = Namespace("http://rdfs.org/ns/void#")
SKOS = Namespace("http://www.w3.org/2004/02/skos/core#")
PERIODO = Namespace("http://n2t.net/ark:/99152/")
FOAF = Namespace("http://xmlns.com/foaf/0.1/")
HOST = Namespace("http://localhost.localdomain:5000/")


def queryForValue(graph, query, bindings, value):
    return next(iter(graph.query(query, initBindings=bindings)))[value].value


def test_context(client):
    res = client.get("/c")
    assert res.status_code == httpx.codes.OK
    assert res.headers["Content-Type"] == "application/json"
    assert res.headers["Cache-Control"] == "public, max-age=0"
    assert list(res.json().keys()) == ["@context"]

    res = client.get("/c", headers={"Accept": "text/html"})
    assert res.status_code == httpx.codes.OK
    assert res.url == f"http://{DEV_SERVER_NAME}/c.json.html"

    res = client.get("/c", params={"version": 1}, headers={"Accept": "text/html"})
    assert res.status_code == httpx.codes.OK
    assert res.url == f"http://{DEV_SERVER_NAME}/c.json.html?version=1"


def test_vocab(client):
    res = client.get("/v", allow_redirects=False)
    assert res.status_code == httpx.codes.SEE_OTHER
    assert urlparse(res.headers["Location"]).path == "/v.ttl.html"

    res = client.get("/v", headers={"Accept": "text/turtle"}, allow_redirects=False)
    assert res.status_code == httpx.codes.SEE_OTHER
    assert urlparse(res.headers["Location"]).path == "/v.ttl"


def test_dataset_description(client):
    res = client.get("/", headers={"Accept": "text/html"}, allow_redirects=False)
    assert res.status_code == httpx.codes.SEE_OTHER
    assert urlparse(res.headers["Location"]).path == "/index.json.html"

    ttl = client.get("/", headers={"Accept": "text/turtle"})
    assert ttl.status_code == httpx.codes.OK
    assert ttl.headers["Content-Type"] == "text/turtle"

    for path in [
        "/.well-known/void",
        "/.wellknown/void",
        "/.well-known/void.ttl",
    ]:
        res = client.get(path)
        assert res.status_code == httpx.codes.OK
        assert res.headers["Content-Type"] == "text/turtle"
        assert res.text == ttl.text

    res = client.get("/.well-known/void.ttl.html")
    assert res.status_code == httpx.codes.OK
    assert res.headers["Content-Type"] == "text/html; charset=utf-8"

    res = client.get("/.well-known/void", headers={"Accept": "text/html"})
    assert res.status_code == httpx.codes.OK
    assert res.headers["Content-Type"] == "text/html; charset=utf-8"
    assert res.url == f"http://{DEV_SERVER_NAME}/.wellknown/void.ttl.html"

    g = Graph()
    g.parse(format="turtle", data=ttl.text)
    assert (PERIODO["p0d"], DCTERMS.provenance, HOST["h#changes"]) in g

    desc = g.value(predicate=RDF.type, object=VOID.DatasetDescription)
    assert desc.n3() == "<http://n2t.net/ark:/99152/p0>"
    title = g.value(subject=desc, predicate=DCTERMS.title)
    assert title.n3() == '"Description of the PeriodO Period Gazetteer"@en'

    q = sparql.prepareQuery(
        """
        SELECT ?count
        WHERE {
            ?d void:classPartition ?p .
            ?p void:class ?class .
            ?p void:entities ?count .
        }
        """,
        initNs={"void": VOID, "skos": SKOS},
    )
    concept_count = queryForValue(g, q, {"class": SKOS.Concept}, "count")
    assert concept_count == 3

    scheme_count = queryForValue(g, q, {"class": SKOS.ConceptScheme}, "count")
    assert scheme_count == 1


def test_dataset_description_linksets(client):
    res = client.get("/.well-known/void")
    g = Graph()
    g.parse(format="turtle", data=res.text)
    q = sparql.prepareQuery(
        """
        SELECT ?triples
        WHERE {
            ?linkset a void:Linkset .
            ?linkset void:subset <http://n2t.net/ark:/99152/p0d> .
            ?linkset void:subjectsTarget <http://n2t.net/ark:/99152/p0d> .
            ?linkset void:linkPredicate ?predicate .
            ?linkset void:objectsTarget ?dataset .
            ?linkset void:triples ?triples .
        }
        """,
        initNs={"void": VOID},
    )
    wikidata = URIRef("http://www.wikidata.org/entity/Q2013")
    triples = queryForValue(
        g, q, {"dataset": wikidata, "predicate": DCTERMS.spatial}, "triples"
    )
    assert triples == 3

    worldcat = URIRef("http://purl.oclc.org/dataset/WorldCat")
    triples = queryForValue(
        g, q, {"dataset": worldcat, "predicate": DCTERMS.isPartOf}, "triples"
    )
    assert triples == 1


def test_add_contributors_to_dataset_description(client, submit_and_merge_patch):
    contribution = (
        URIRef("http://n2t.net/ark:/99152/p0d"),
        DCTERMS.contributor,
        URIRef("https://orcid.org/1234-5678-9101-112X"),
    )

    data = client.get("/", headers={"Accept": "text/turtle"}).text
    g = Graph().parse(format="turtle", data=data)
    assert contribution not in g

    submit_and_merge_patch("test-patch-replace-values-1.json")

    data = client.get("/", headers={"Accept": "text/turtle"}).text
    g = Graph().parse(format="turtle", data=data)
    assert contribution in g


def test_dataset(client):
    res = client.get("/d", allow_redirects=False)
    assert res.status_code == httpx.codes.SEE_OTHER
    assert urlparse(res.headers["Location"]).path == "/d/"


def test_dataset_data_even_if_html_accepted(client):
    res = client.get("/d/", headers={"Accept": "text/html"}, allow_redirects=False)
    assert res.status_code == httpx.codes.OK
    assert res.headers["Content-Type"] == "application/json"
    assert res.headers["Cache-Control"] == "public, max-age=0"
    assert (
        res.headers["Content-Disposition"]
        == 'attachment; filename="periodo-dataset.json"'
    )


def test_dataset_data(client):
    res = client.get("/d/")
    assert res.status_code == httpx.codes.OK
    assert res.headers["Content-Type"] == "application/json"
    assert res.headers["Cache-Control"] == "public, max-age=0"

    context = res.json()["@context"]
    assert context == [
        "http://localhost.localdomain:5000/c",
        {"@base": "http://n2t.net/ark:/99152/"},
    ]
    res = client.get("/d.json")
    assert res.status_code == httpx.codes.OK
    assert res.headers["Content-Type"] == "application/json"
    assert (
        res.headers["Content-Disposition"]
        == 'attachment; filename="periodo-dataset.json"'
    )
    assert "Date" in res.headers
    res = client.get("/d.jsonld")
    assert res.status_code == httpx.codes.OK
    assert res.headers["Content-Type"] == "application/ld+json"
    assert (
        res.headers["Content-Disposition"]
        == 'attachment; filename="periodo-dataset.jsonld"'
    )
    res = client.get("/d/", headers={"Accept": "application/ld+json"})
    assert res.status_code == httpx.codes.OK
    assert res.headers["Content-Type"] == "application/ld+json"
    res = client.get(
        "/d.json",
        headers={
            "Accept": "text/html,application/xhtml+xml,"
            + "application/xml;q=0.9,image/webp,*/*;q=0.8"
        },
    )
    assert res.status_code == httpx.codes.OK
    assert res.headers["Content-Type"] == "application/json"
    res = client.get(
        "/d.jsonld",
        headers={
            "Accept": "text/html,application/xhtml+xml,"
            + "application/xml;q=0.9,image/webp,*/*;q=0.8"
        },
    )
    assert res.status_code == httpx.codes.OK
    assert res.headers["Content-Type"] == "application/ld+json"

    res = client.get("/d/", headers={"Accept": "application/ld+json"})
    jsonld = res.json()

    res = client.get("/c")
    context = res.json()

    g = Graph().parse(data=json.dumps({**jsonld, **context}), format="json-ld")
    assert (PERIODO["p0d/#authorities"], FOAF.isPrimaryTopicOf, HOST["d/"]) in g
    assert (HOST["d/"], VOID.inDataset, HOST["d"]) in g
    assert (HOST["d"], DCTERMS.provenance, HOST["h#changes"]) in g


def test_inline_context(client):
    res = client.get("/d.json?inline-context")
    assert res.status_code == httpx.codes.OK
    assert res.headers["Content-Type"] == "application/json"
    assert (
        res.headers["Content-Disposition"]
        == 'attachment; filename="periodo-dataset.json"'
    )
    context = res.json()["@context"]
    assert type(context) is dict
    assert "@base" in context
    assert context["@base"] == "http://n2t.net/ark:/99152/"


def test_if_none_match(client):
    res = client.get("/d/")
    assert res.status_code == httpx.codes.OK
    assert res.headers["Etag"] == 'W/"periodo-dataset-version-1"'
    res = client.get("/d/", headers={"If-None-Match": 'W/"periodo-dataset-version-1"'})
    assert res.status_code == httpx.codes.NOT_MODIFIED


def test_authority(client):
    res = client.get("/trgkv", allow_redirects=False)
    assert res.status_code == httpx.codes.SEE_OTHER
    assert urlparse(res.headers["Location"]).path == "/"
    assert urlparse(res.headers["Location"]).query == urlencode(
        {
            "page": "authority-view",
            "backendID": f"web-http://{DEV_SERVER_NAME}/",
            "authorityID": "p0trgkv",
        }
    )

    res = client.get(
        "/trgkv", headers={"Accept": "application/json"}, allow_redirects=False
    )
    assert res.status_code == httpx.codes.SEE_OTHER
    assert urlparse(res.headers["Location"]).path == "/trgkv.json"

    res = client.get(
        "/trgkv", headers={"Accept": "application/ld+json"}, allow_redirects=False
    )
    assert res.status_code == httpx.codes.SEE_OTHER
    assert urlparse(res.headers["Location"]).path == "/trgkv.jsonld"

    res = client.get("/trgkv", headers={"Accept": "text/html"}, allow_redirects=False)
    assert res.status_code == httpx.codes.SEE_OTHER
    assert urlparse(res.headers["Location"]).path == "/"
    assert urlparse(res.headers["Location"]).query == urlencode(
        {
            "page": "authority-view",
            "backendID": f"web-http://{DEV_SERVER_NAME}/",
            "authorityID": "p0trgkv",
        }
    )

    res = client.get("/trgkv/")
    assert res.status_code == httpx.codes.NOT_FOUND

    res = client.get("/trgkv", headers={"Accept": "text/turtle"}, allow_redirects=False)
    assert res.status_code == httpx.codes.SEE_OTHER
    assert urlparse(res.headers["Location"]).path == "/trgkv.ttl"


def test_authority_json(client):
    res = client.get("/trgkv.json")
    assert res.status_code == httpx.codes.OK
    assert res.headers["Content-Type"] == "application/json"
    assert (
        res.headers["Content-Disposition"]
        == 'attachment; filename="periodo-authority-trgkv.json"'
    )
    context = res.json()["@context"]
    assert context == [
        "http://localhost.localdomain:5000/c",
        {"@base": "http://n2t.net/ark:/99152/"},
    ]

    res = client.get("/trgkv.jsonld")
    assert res.status_code == httpx.codes.OK
    assert res.headers["Content-Type"] == "application/ld+json"
    assert (
        res.headers["Content-Disposition"]
        == 'attachment; filename="periodo-authority-trgkv.jsonld"'
    )

    jsonld = res.json()
    context = json.loads(client.get("/c").text)
    g = Graph().parse(data=json.dumps({**jsonld, **context}), format="json-ld")
    assert g.value(predicate=RDF.type, object=RDF.Bag) is None
    assert (PERIODO["p0trgkv"], FOAF.isPrimaryTopicOf, HOST["trgkv.jsonld"]) in g
    assert (HOST["trgkv.jsonld"], VOID.inDataset, HOST["d"]) in g

    res = client.get("/trgkv.json/")
    assert res.status_code == httpx.codes.NOT_FOUND
    res = client.get("/trgkv.jsonld/")
    assert res.status_code == httpx.codes.NOT_FOUND

    res = client.get("/trgkv.json.html")
    assert res.status_code == httpx.codes.OK
    assert res.headers["Content-Type"] == "text/html; charset=utf-8"
    assert "Content-Disposition" not in res.headers


def test_authority_turtle(client):
    res = client.get("/trgkv.ttl")
    assert res.status_code == httpx.codes.OK
    assert res.headers["Content-Type"] == "text/turtle"
    assert res.headers["Cache-Control"] == "public, max-age={}".format(cache.SHORT_TIME)
    assert (
        res.headers["Content-Disposition"]
        == 'attachment; filename="periodo-authority-trgkv.ttl"'
    )

    g = Graph().parse(data=res.text, format="turtle")
    assert g.value(predicate=RDF.type, object=RDF.Bag) is None
    assert (PERIODO["p0trgkv"], FOAF.isPrimaryTopicOf, HOST["trgkv.ttl"]) in g
    assert (HOST["trgkv.ttl"], VOID.inDataset, HOST["d"]) in g

    res = client.get("/trgkv.ttl.html")
    assert res.status_code == httpx.codes.OK
    assert res.headers["Content-Type"] == "text/html; charset=utf-8"
    assert res.headers["Cache-Control"] == "public, max-age={}".format(cache.SHORT_TIME)
    assert "Date" in res.headers
    assert "Content-Disposition" not in res.headers

    res = client.get("/trgkv.ttl/")
    assert res.status_code == httpx.codes.NOT_FOUND


def test_period(client):
    res = client.get("/trgkvwbjd", allow_redirects=False)
    assert res.status_code == httpx.codes.SEE_OTHER
    assert urlparse(res.headers["Location"]).path == "/"
    assert urlparse(res.headers["Location"]).query == urlencode(
        {
            "page": "period-view",
            "backendID": f"web-http://{DEV_SERVER_NAME}/",
            "authorityID": "p0trgkv",
            "periodID": "p0trgkvwbjd",
        }
    )

    res = client.get(
        "/trgkvwbjd", headers={"Accept": "application/json"}, allow_redirects=False
    )
    assert res.status_code == httpx.codes.SEE_OTHER
    assert urlparse(res.headers["Location"]).path == "/trgkvwbjd.json"

    res = client.get(
        "/trgkvwbjd", headers={"Accept": "application/ld+json"}, allow_redirects=False
    )
    assert res.status_code == httpx.codes.SEE_OTHER
    assert urlparse(res.headers["Location"]).path == "/trgkvwbjd.jsonld"

    res = client.get(
        "/trgkvwbjd", headers={"Accept": "text/html"}, allow_redirects=False
    )
    assert res.status_code == httpx.codes.SEE_OTHER
    assert urlparse(res.headers["Location"]).path == "/"
    assert urlparse(res.headers["Location"]).query == urlencode(
        {
            "page": "period-view",
            "backendID": f"web-http://{DEV_SERVER_NAME}/",
            "authorityID": "p0trgkv",
            "periodID": "p0trgkvwbjd",
        }
    )

    res = client.get(
        "/trgkvwbjd", headers={"Accept": "text/turtle"}, allow_redirects=False
    )
    assert res.status_code == httpx.codes.SEE_OTHER
    assert urlparse(res.headers["Location"]).path == "/trgkvwbjd.ttl"


def test_period_json(client):
    res = client.get("/trgkvwbjd.json")
    assert res.status_code == httpx.codes.OK
    assert res.headers["Content-Type"] == "application/json"
    assert (
        res.headers["Content-Disposition"]
        == 'attachment; filename="periodo-period-trgkvwbjd.json"'
    )
    context = res.json()["@context"]
    assert context == [
        "http://localhost.localdomain:5000/c",
        {"@base": "http://n2t.net/ark:/99152/"},
    ]

    res = client.get("/trgkvwbjd.jsonld")
    assert res.status_code == httpx.codes.OK
    assert res.headers["Content-Type"] == "application/ld+json"
    assert (
        res.headers["Content-Disposition"]
        == 'attachment; filename="periodo-period-trgkvwbjd.jsonld"'
    )

    jsonld = res.json()
    context = json.loads(client.get("/c").text)
    g = Graph().parse(data=json.dumps({**jsonld, **context}), format="json-ld")
    assert g.value(predicate=RDF.type, object=SKOS.ConceptScheme) is None
    assert (
        PERIODO["p0trgkvwbjd"],
        FOAF.isPrimaryTopicOf,
        HOST["trgkvwbjd.jsonld"],
    ) in g
    assert (HOST["trgkvwbjd.jsonld"], VOID.inDataset, HOST["d"]) in g
    assert (PERIODO["p0trgkvwbjd"], SKOS.inScheme, PERIODO["p0trgkv"]) in g

    res = client.get("/trgkvwbjd.json.html")
    assert res.status_code == httpx.codes.OK
    assert res.headers["Content-Type"] == "text/html; charset=utf-8"
    assert "Content-Disposition" not in res.headers


def test_period_turtle(client):
    res = client.get("/trgkvwbjd.ttl")
    assert res.status_code == httpx.codes.OK
    assert res.headers["Content-Type"] == "text/turtle"
    assert res.headers["Cache-Control"] == "public, max-age={}".format(cache.SHORT_TIME)
    assert (
        res.headers["Content-Disposition"]
        == 'attachment; filename="periodo-period-trgkvwbjd.ttl"'
    )

    g = Graph().parse(data=res.text, format="turtle")
    assert g.value(predicate=RDF.type, object=SKOS.ConceptScheme) is None
    assert (PERIODO["p0trgkvwbjd"], FOAF.isPrimaryTopicOf, HOST["trgkvwbjd.ttl"]) in g
    assert (HOST["trgkvwbjd.ttl"], VOID.inDataset, HOST["d"]) in g
    assert (PERIODO["p0trgkvwbjd"], SKOS.inScheme, PERIODO["p0trgkv"]) in g

    res = client.get("/trgkvwbjd.ttl.html")
    assert res.status_code == httpx.codes.OK
    assert res.headers["Content-Type"] == "text/html; charset=utf-8"
    assert res.headers["Cache-Control"] == "public, max-age={}".format(cache.SHORT_TIME)
    assert "Content-Disposition" not in res.headers


def test_d_turtle(client):
    res = client.get("/d.ttl")
    assert res.status_code == httpx.codes.OK
    assert res.headers["Content-Type"] == "text/turtle"
    assert res.headers["Cache-Control"] == "public, max-age={}".format(cache.SHORT_TIME)
    assert (
        res.headers["Content-Disposition"]
        == 'attachment; filename="periodo-dataset.ttl"'
    )

    g = Graph().parse(data=res.text, format="turtle")
    assert (PERIODO["p0d/#authorities"], FOAF.isPrimaryTopicOf, HOST["d.ttl"]) in g
    assert (HOST["d.ttl"], VOID.inDataset, HOST["d"]) in g
    assert (HOST["d"], DCTERMS.provenance, HOST["h#changes"]) in g

    res = client.get("/d.ttl/")
    assert res.status_code == httpx.codes.NOT_FOUND


def test_dataset_turtle(client):
    res = client.get("/dataset.ttl")
    assert res.status_code == httpx.codes.OK
    assert res.headers["Content-Type"] == "text/turtle"
    assert res.headers["Cache-Control"] == "public, max-age={}".format(cache.SHORT_TIME)
    assert (
        res.headers["Content-Disposition"]
        == 'attachment; filename="periodo-dataset.ttl"'
    )

    g = Graph().parse(data=res.text, format="turtle")
    assert (
        PERIODO["p0d/#authorities"],
        FOAF.isPrimaryTopicOf,
        HOST["dataset.ttl"],
    ) in g
    assert (HOST["dataset.ttl"], VOID.inDataset, HOST["d"]) in g
    assert (HOST["d"], DCTERMS.provenance, HOST["h#changes"]) in g

    res = client.get("/dataset.ttl/")
    assert res.status_code == httpx.codes.NOT_FOUND


def test_dataset_csv(client):
    res = client.get("/dataset.csv")
    data = res.text
    if not res.status_code == httpx.codes.OK:
        print(data)
    assert res.status_code == httpx.codes.OK
    assert res.headers["Content-Type"] == "text/csv"
    assert res.headers["Cache-Control"] == "public, max-age={}".format(
        cache.MEDIUM_TIME
    )
    assert (
        res.headers["Content-Disposition"]
        == 'attachment; filename="periodo-dataset.csv"'
    )

    rows = csv.reader(data.splitlines())
    assert next(rows) == [
        "period",
        "label",
        "spatial_coverage",
        "gazetteer_links",
        "start",
        "stop",
        "authority",
        "source",
        "publication_year",
        "derived_periods",
        "broader_periods",
        "narrower_periods",
    ]
    assert next(rows) == [
        "http://n2t.net/ark:/99152/p0trgkvkhrv",
        "Iron Age",
        "Spain",
        "http://www.wikidata.org/entity/Q29",
        "-0799",
        "-0549",
        "http://n2t.net/ark:/99152/p0trgkv",
        "The Corinthian, Attic, and Lakonian pottery from Sardis"
        + " | Schaeffer, Judith Snyder, 1937-"
        + " | Greenewalt, Crawford H. (Crawford Hallock), 1937-2012."
        + " | Ramage, Nancy H., 1942-",
        "1997",
        "",
        "http://n2t.net/ark:/99152/p0trgkv4kxb",
        "",
    ]


def test_h_nt(client, submit_and_merge_patch):

    submit_and_merge_patch("test-patch-replace-values-1.json")

    res = client.get("/h.nt")
    assert res.status_code == httpx.codes.OK
    assert res.headers["Content-Type"] == "application/n-triples"
    assert res.headers["X-Accel-Expires"] == f"{cache.MEDIUM_TIME}"
    assert res.headers["Cache-Control"] == "public, max-age=0"
    assert (
        res.headers["Content-Disposition"]
        == 'attachment; filename="periodo-history.nt"'
    )

    g = Graph()
    g.parse(data=res.text, format="nt")
    assert (HOST["h#patch-1"], FOAF.page, HOST["patches/1/patch.jsonpatch"]) in g
    assert (HOST["d"], DCTERMS.provenance, HOST["h#changes"]) in g

    res = client.get("/h.nt/")
    assert res.status_code == httpx.codes.NOT_FOUND


def test_h_turtle(client):
    res = client.get("/h.ttl", allow_redirects=False)
    assert res.status_code == httpx.codes.MOVED_PERMANENTLY
    assert res.headers["Location"] == str(HOST["h.nt"])


def test_history_nt(client, submit_and_merge_patch):

    submit_and_merge_patch("test-patch-replace-values-1.json")

    res = client.get("/history.nt")
    assert res.headers["Content-Type"] == "application/n-triples"
    assert res.headers["X-Accel-Expires"] == f"{cache.MEDIUM_TIME}"
    assert res.headers["Cache-Control"] == "public, max-age=0"
    assert (
        res.headers["Content-Disposition"]
        == 'attachment; filename="periodo-history.nt"'
    )

    g = Graph()
    g.parse(data=res.text, format="turtle")
    assert (HOST["h#patch-1"], FOAF.page, HOST["patches/1/patch.jsonpatch"]) in g
    assert (HOST["d"], DCTERMS.provenance, HOST["h#changes"]) in g

    res = client.get("/history.nt/")
    assert res.status_code == httpx.codes.NOT_FOUND


def test_history_json(client):
    res = client.get("/history.json")
    assert res.status_code == httpx.codes.NOT_FOUND


def test_export(client):
    res = client.get("/export.sql")
    assert res.status_code == httpx.codes.OK
    assert res.headers["Content-Type"] == "text/plain"
