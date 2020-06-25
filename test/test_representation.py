import os
import tempfile
import unittest
import http.client
import json
import csv
from rdflib import Graph, URIRef
from rdflib.plugins import sparql
from rdflib.namespace import Namespace, RDF, DCTERMS
from urllib.parse import urlparse
from flask_principal import ActionNeed
from .filepath import filepath
from periodo import app, commands, database, auth, cache

VOID = Namespace('http://rdfs.org/ns/void#')
SKOS = Namespace('http://www.w3.org/2004/02/skos/core#')
PERIODO = Namespace('http://n2t.net/ark:/99152/')
FOAF = Namespace('http://xmlns.com/foaf/0.1/')
HOST = Namespace('http://localhost.localdomain:5000/')


class TestRepresentationsAndRedirects(unittest.TestCase):

    def setUp(self):
        self.db_fd, app.config['DATABASE'] = tempfile.mkstemp()
        app.config['TESTING'] = True
        self.client = app.test_client()
        with open(filepath('test-patch-replace-values-1.json')) as f:
            self.patch = f.read()
        commands.init_db()
        commands.load_data(filepath('test-data.json'))
        with app.app_context():
            self.user_identity = auth.add_user_or_update_credentials({
                'name': 'Regular Gal',
                'access_token': '5005eb18-be6b-4ac0-b084-0443289b3378',
                'expires_in': 631138518,
                'orcid': '1234-5678-9101-112X',
            })
            self.admin_identity = auth.add_user_or_update_credentials({
                'name': 'Super Admin',
                'access_token': 'f7c64584-0750-4cb6-8c81-2932f5daabb8',
                'expires_in': 3600,
                'orcid': '1211-1098-7654-321X',
            }, (ActionNeed('accept-patch'),))
            database.commit()

    def tearDown(self):
        os.close(self.db_fd)
        os.unlink(app.config['DATABASE'])

    def test_context(self):
        res1 = self.client.get('/c', buffered=True)
        self.assertEqual(res1.status_code, http.client.OK)
        self.assertEqual(res1.headers['Content-Type'], 'application/json')
        self.assertEqual(
            list(json.loads(res1.get_data(as_text=True)).keys()), ['@context'])

    def test_vocab(self):
        res1 = self.client.get('/v', buffered=True)
        self.assertEqual(res1.status_code, http.client.SEE_OTHER)
        self.assertEqual(
            urlparse(res1.headers['Location']).path, '/v.ttl.html')

        res2 = self.client.get(
            '/v', headers={'Accept': 'text/turtle'}, buffered=True)
        self.assertEqual(res2.status_code, http.client.SEE_OTHER)
        self.assertEqual(urlparse(res2.headers['Location']).path, '/v.ttl')

    def test_dataset_description(self):
        res1 = self.client.get(
            '/', headers={'Accept': 'text/html'}, buffered=True)
        self.assertEqual(res1.status_code, http.client.SEE_OTHER)
        self.assertEqual(urlparse(res1.headers['Location']).path,
                         '/index.json.html')

        res2 = self.client.get('/', headers={'Accept': 'text/turtle'})
        self.assertEqual(res2.status_code, http.client.OK)
        self.assertEqual(res2.headers['Content-Type'], 'text/turtle')

        res3 = self.client.get('/.well-known/void')
        self.assertEqual(res3.status_code, http.client.OK)
        self.assertEqual(res3.headers['Content-Type'], 'text/turtle')
        self.assertEqual(res3.get_data(as_text=True),
                         res2.get_data(as_text=True))

        res4 = self.client.get('/.wellknown/void')
        self.assertEqual(res4.status_code, http.client.OK)
        self.assertEqual(res4.headers['Content-Type'], 'text/turtle')
        self.assertEqual(res4.get_data(as_text=True),
                         res3.get_data(as_text=True))

        res5 = self.client.get('/.well-known/void.ttl')
        self.assertEqual(res5.status_code, http.client.OK)
        self.assertEqual(res5.headers['Content-Type'], 'text/turtle')
        self.assertEqual(res5.get_data(as_text=True),
                         res4.get_data(as_text=True))

        res6 = self.client.get('/.well-known/void.ttl.html')
        self.assertEqual(res6.status_code, http.client.OK)
        self.assertEqual(res6.headers['Content-Type'], 'text/html')

        g = Graph()
        g.parse(format='turtle', data=res2.get_data(as_text=True))
        self.assertIn(
            (PERIODO['p0d'], DCTERMS.provenance, HOST['h#changes']), g)
        desc = g.value(predicate=RDF.type, object=VOID.DatasetDescription)
        self.assertEqual(
            desc.n3(), '<http://n2t.net/ark:/99152/p0>')
        title = g.value(subject=desc, predicate=DCTERMS.title)
        self.assertEqual(
            title.n3(), '"Description of the PeriodO Period Gazetteer"@en')
        q = sparql.prepareQuery('''
SELECT ?count
WHERE {
  ?d void:classPartition ?p .
  ?p void:class ?class .
  ?p void:entities ?count .
}
''', initNs={'void': VOID, 'skos': SKOS})
        concept_count = next(iter(g.query(
            q, initBindings={'class': SKOS.Concept})))['count'].value
        self.assertEqual(concept_count, 3)
        scheme_count = next(iter(g.query(
            q, initBindings={'class': SKOS.ConceptScheme})))['count'].value
        self.assertEqual(scheme_count, 1)

    def test_dataset_description_linksets(self):
        res = self.client.get('/.well-known/void')
        self.assertEqual(res.status_code, http.client.OK)
        self.assertEqual(res.headers['Content-Type'], 'text/turtle')
        g = Graph()
        g.parse(format='turtle', data=res.get_data(as_text=True))
        q = sparql.prepareQuery('''
SELECT ?triples
WHERE {
  ?linkset a void:Linkset .
  ?linkset void:subset <http://n2t.net/ark:/99152/p0d> .
  ?linkset void:subjectsTarget <http://n2t.net/ark:/99152/p0d> .
  ?linkset void:linkPredicate ?predicate .
  ?linkset void:objectsTarget ?dataset .
  ?linkset void:triples ?triples .
}
''', initNs={'void': VOID})
        wikidata = URIRef('http://www.wikidata.org/entity/Q2013')
        triples = next(iter(g.query(
            q, initBindings={'dataset': wikidata,
                             'predicate': DCTERMS.spatial})))['triples'].value
        self.assertEqual(triples, 3)

        worldcat = URIRef('http://purl.oclc.org/dataset/WorldCat')
        triples = next(iter(g.query(
            q, initBindings={'dataset': worldcat,
                             'predicate': DCTERMS.isPartOf})))['triples'].value
        self.assertEqual(triples, 1)

    def test_add_contributors_to_dataset_description(self):
        contribution = (URIRef('http://n2t.net/ark:/99152/p0d'),
                        DCTERMS.contributor,
                        URIRef('https://orcid.org/1234-5678-9101-112X'))
        data = self.client.get(
            '/', headers={'Accept': 'text/turtle'}).get_data(as_text=True)
        g = Graph().parse(format='turtle', data=data)
        self.assertNotIn(contribution, g)
        with self.client as client:
            res = client.patch(
                '/d/',
                data=self.patch,
                content_type='application/json',
                headers={'Authorization': 'Bearer '
                         + 'NTAwNWViMTgtYmU2Yi00YWMwLWIwODQtMDQ0MzI4OWIzMzc4'})
            res = client.post(
                urlparse(res.headers['Location']).path + 'merge',
                buffered=True,
                headers={'Authorization': 'Bearer '
                         + 'ZjdjNjQ1ODQtMDc1MC00Y2I2LThjODEtMjkzMmY1ZGFhYmI4'})
        data = self.client.get(
            '/', headers={'Accept': 'text/turtle'}).get_data(as_text=True)
        g = Graph().parse(format='turtle', data=data)
        self.assertIn(contribution, g)

    def test_dataset(self):
        res = self.client.get('/d')
        self.assertEqual(res.status_code, http.client.SEE_OTHER)
        self.assertEqual(urlparse(res.headers['Location']).path, '/d/')

    def test_dataset_html_redirect(self):
        res = self.client.get('/d/', headers={'Accept': 'text/html'})
        self.assertEqual(res.status_code, http.client.TEMPORARY_REDIRECT)
        self.assertEqual(urlparse(res.headers['Location']).path, '/d.json')

    def test_dataset_data(self):
        res1 = self.client.get('/d/')
        self.assertEqual(res1.status_code, http.client.OK)
        self.assertEqual(res1.headers['Content-Type'], 'application/json')
        self.assertEqual(
            res1.headers['Cache-Control'], 'public, max-age=0')

        context = json.loads(res1.get_data(as_text=True))['@context']
        self.assertEqual(context, [
            'http://localhost.localdomain:5000/c',
            {'@base': 'http://n2t.net/ark:/99152/'}])
        res2 = self.client.get('/d.json')
        self.assertEqual(res2.status_code, http.client.OK)
        self.assertEqual(res2.headers['Content-Type'], 'application/json')
        self.assertEqual(
            res2.headers['Content-Disposition'],
            'attachment; filename="periodo-dataset.json"')
        self.assertIn('Date', res2.headers)
        res3 = self.client.get('/d.jsonld')
        self.assertEqual(res3.status_code, http.client.OK)
        self.assertEqual(res3.headers['Content-Type'], 'application/ld+json')
        self.assertEqual(
            res3.headers['Content-Disposition'],
            'attachment; filename="periodo-dataset.json"')
        res4 = self.client.get(
            '/d/', headers={'Accept': 'application/ld+json'})
        self.assertEqual(res4.status_code, http.client.OK)
        self.assertEqual(res4.headers['Content-Type'], 'application/ld+json')
        res5 = self.client.get(
            '/d.json',
            headers={'Accept': 'text/html,application/xhtml+xml,'
                     + 'application/xml;q=0.9,image/webp,*/*;q=0.8'})
        self.assertEqual(res5.status_code, http.client.OK)
        self.assertEqual(res5.headers['Content-Type'], 'application/json')
        res6 = self.client.get(
            '/d.jsonld',
            headers={'Accept': 'text/html,application/xhtml+xml,'
                     + 'application/xml;q=0.9,image/webp,*/*;q=0.8'})
        self.assertEqual(res6.status_code, http.client.OK)
        self.assertEqual(res6.headers['Content-Type'], 'application/ld+json')

        jsonld = json.loads(res4.get_data(as_text=True))

        res7 = self.client.get('/c', buffered=True)
        self.assertEqual(
            res7.headers['Cache-Control'], 'public, max-age=0')
        context = json.loads(res7.get_data(as_text=True))

        g = Graph().parse(
            data=json.dumps({**jsonld, **context}), format='json-ld')
        self.assertIn((PERIODO['p0d/#authorities'],
                       FOAF.isPrimaryTopicOf, HOST['d/']), g)
        self.assertIn((HOST['d/'],
                       VOID.inDataset, HOST['d']), g)
        self.assertIn((HOST['d'],
                       DCTERMS.provenance, HOST['h#changes']), g)

    def test_inline_context(self):
        res1 = self.client.get('/d.json?inline-context')
        self.assertEqual(res1.status_code, http.client.OK)
        self.assertEqual(res1.headers['Content-Type'], 'application/json')
        self.assertEqual(
            res1.headers['Content-Disposition'],
            'attachment; filename="periodo-dataset.json"')
        context = json.loads(res1.get_data(as_text=True))['@context']
        self.assertIs(type(context), dict)
        self.assertIn('@base', context)
        self.assertEqual(context['@base'], 'http://n2t.net/ark:/99152/')

    def test_if_none_match(self):
        res1 = self.client.get('/d/')
        self.assertEqual(res1.status_code, http.client.OK)
        self.assertEqual(res1.get_etag(), ('periodo-dataset-version-1', True))
        res2 = self.client.get('/d/', buffered=True, headers={
            'If-None-Match': 'W/"periodo-dataset-version-1"'})
        self.assertEqual(res2.status_code, http.client.NOT_MODIFIED)

    def test_authority(self):
        res1 = self.client.get('/trgkv')
        self.assertEqual(res1.status_code, http.client.SEE_OTHER)
        self.assertEqual(urlparse(res1.headers['Location']).path, '/')
        self.assertEqual(urlparse(res1.headers['Location']).query, 'page=authority-view&backendID=web-http%3A%2F%2Flocalhost.localdomain%3A5000%2F&authorityID=p0trgkv') # noqa

        res2 = self.client.get(
            '/trgkv', headers={'Accept': 'application/json'})
        self.assertEqual(res2.status_code, http.client.SEE_OTHER)
        self.assertEqual(
            urlparse(res2.headers['Location']).path, '/trgkv.json')

        res3 = self.client.get(
            '/trgkv', headers={'Accept': 'application/ld+json'})
        self.assertEqual(res3.status_code, http.client.SEE_OTHER)
        self.assertEqual(
            urlparse(res3.headers['Location']).path, '/trgkv.jsonld')

        res4 = self.client.get('/trgkv', headers={'Accept': 'text/html'})
        self.assertEqual(res4.status_code, http.client.SEE_OTHER)
        self.assertEqual(urlparse(res4.headers['Location']).path, '/')
        self.assertEqual(urlparse(res4.headers['Location']).query, 'page=authority-view&backendID=web-http%3A%2F%2Flocalhost.localdomain%3A5000%2F&authorityID=p0trgkv') # noqa

        res5 = self.client.get('/trgkv/')
        self.assertEqual(res5.status_code, http.client.NOT_FOUND)

        res6 = self.client.get(
            '/trgkv', headers={'Accept': 'text/turtle'})
        self.assertEqual(res6.status_code, http.client.SEE_OTHER)
        self.assertEqual(
            urlparse(res6.headers['Location']).path, '/trgkv.ttl')

    def test_authority_json(self):
        res1 = self.client.get('/trgkv.json')
        self.assertEqual(res1.status_code, http.client.OK)
        self.assertEqual(res1.headers['Content-Type'], 'application/json')
        self.assertEqual(
            res1.headers['Content-Disposition'],
            'attachment; filename="periodo-authority-trgkv.json"')
        context = json.loads(res1.get_data(as_text=True))['@context']
        self.assertEqual(context, [
            'http://localhost.localdomain:5000/c',
            {'@base': 'http://n2t.net/ark:/99152/'}])

        res2 = self.client.get('/trgkv.jsonld')
        self.assertEqual(res2.status_code, http.client.OK)
        self.assertEqual(res2.headers['Content-Type'], 'application/ld+json')
        self.assertEqual(
            res2.headers['Content-Disposition'],
            'attachment; filename="periodo-authority-trgkv.json"')

        jsonld = json.loads(res2.get_data(as_text=True))
        context = json.loads(self.client.get('/c', buffered=True)
                             .get_data(as_text=True))
        g = Graph().parse(
            data=json.dumps({**jsonld, **context}), format='json-ld')
        self.assertIsNone(g.value(predicate=RDF.type, object=RDF.Bag))
        self.assertIn((PERIODO['p0trgkv'],
                       FOAF.isPrimaryTopicOf, HOST['trgkv.jsonld']), g)
        self.assertIn((HOST['trgkv.jsonld'],
                       VOID.inDataset, HOST['d']), g)

        res3 = self.client.get('/trgkv.json/')
        self.assertEqual(res3.status_code, http.client.NOT_FOUND)
        res4 = self.client.get('/trgkv.jsonld/')
        self.assertEqual(res4.status_code, http.client.NOT_FOUND)

        res5 = self.client.get('/trgkv.json.html')
        self.assertEqual(res5.status_code, http.client.OK)
        self.assertEqual(res5.headers['Content-Type'], 'text/html')

    def test_authority_turtle(self):
        res1 = self.client.get('/trgkv.ttl')
        self.assertEqual(res1.status_code, http.client.OK)
        self.assertEqual(res1.headers['Content-Type'], 'text/turtle')
        self.assertEqual(
            res1.headers['Cache-Control'],
            'public, max-age={}'.format(cache.SHORT_TIME))
        self.assertEqual(
            res1.headers['Content-Disposition'],
            'attachment; filename="periodo-authority-trgkv.ttl"')

        g = Graph().parse(data=res1.get_data(as_text=True), format='turtle')
        self.assertIsNone(g.value(predicate=RDF.type, object=RDF.Bag))
        self.assertIn((PERIODO['p0trgkv'],
                       FOAF.isPrimaryTopicOf, HOST['trgkv.ttl']), g)
        self.assertIn((HOST['trgkv.ttl'],
                       VOID.inDataset, HOST['d']), g)

        res2 = self.client.get('/trgkv.ttl.html')
        self.assertEqual(res2.status_code, http.client.OK)
        self.assertEqual(res2.headers['Content-Type'], 'text/html')
        self.assertEqual(
            res2.headers['Cache-Control'],
            'public, max-age={}'.format(cache.SHORT_TIME))
        self.assertIn('Date', res2.headers)

        res3 = self.client.get('/trgkv.ttl/')
        self.assertEqual(res3.status_code, http.client.NOT_FOUND)

    def test_period(self):
        res1 = self.client.get('/trgkvwbjd')
        self.assertEqual(res1.status_code, http.client.SEE_OTHER)
        self.assertEqual(urlparse(res1.headers['Location']).path, '/')
        self.assertEqual(urlparse(res1.headers['Location']).query, 'page=period-view&backendID=web-http%3A%2F%2Flocalhost.localdomain%3A5000%2F&authorityID=p0trgkv&periodID=p0trgkvwbjd') # noqa
        res2 = self.client.get(
            '/trgkvwbjd', headers={'Accept': 'application/json'})
        self.assertEqual(res2.status_code, http.client.SEE_OTHER)
        self.assertEqual(
            urlparse(res2.headers['Location']).path, '/trgkvwbjd.json')
        res3 = self.client.get(
            '/trgkvwbjd', headers={'Accept': 'application/ld+json'})
        self.assertEqual(res3.status_code, http.client.SEE_OTHER)
        self.assertEqual(
            urlparse(res3.headers['Location']).path, '/trgkvwbjd.jsonld')
        res4 = self.client.get(
            '/trgkvwbjd', headers={'Accept': 'text/html'})
        self.assertEqual(res4.status_code, http.client.SEE_OTHER)
        self.assertEqual(urlparse(res4.headers['Location']).path, '/')
        self.assertEqual(urlparse(res4.headers['Location']).query, 'page=period-view&backendID=web-http%3A%2F%2Flocalhost.localdomain%3A5000%2F&authorityID=p0trgkv&periodID=p0trgkvwbjd') # noqa
        res5 = self.client.get(
            '/trgkvwbjd', headers={'Accept': 'text/turtle'})
        self.assertEqual(res5.status_code, http.client.SEE_OTHER)
        self.assertEqual(
            urlparse(res5.headers['Location']).path, '/trgkvwbjd.ttl')

    def test_period_json(self):
        res1 = self.client.get('/trgkvwbjd.json')
        self.assertEqual(res1.status_code, http.client.OK)
        self.assertEqual(res1.headers['Content-Type'], 'application/json')
        self.assertEqual(
            res1.headers['Content-Disposition'],
            'attachment; filename="periodo-period-trgkvwbjd.json"')
        context = json.loads(res1.get_data(as_text=True))['@context']
        self.assertEqual(context, [
            'http://localhost.localdomain:5000/c',
            {'@base': 'http://n2t.net/ark:/99152/'}])

        res2 = self.client.get('/trgkvwbjd.jsonld')
        self.assertEqual(res2.status_code, http.client.OK)
        self.assertEqual(res2.headers['Content-Type'], 'application/ld+json')
        self.assertEqual(
            res2.headers['Content-Disposition'],
            'attachment; filename="periodo-period-trgkvwbjd.json"')

        jsonld = json.loads(res1.get_data(as_text=True))
        context = json.loads(self.client.get('/c', buffered=True)
                             .get_data(as_text=True))
        g = Graph().parse(
            data=json.dumps({**jsonld, **context}), format='json-ld')
        self.assertIsNone(
            g.value(predicate=RDF.type, object=SKOS.ConceptScheme))
        self.assertIn((PERIODO['p0trgkvwbjd'],
                       FOAF.isPrimaryTopicOf, HOST['trgkvwbjd.json']), g)
        self.assertIn((HOST['trgkvwbjd.json'],
                       VOID.inDataset, HOST['d']), g)
        self.assertIn((PERIODO['p0trgkvwbjd'],
                       SKOS.inScheme, PERIODO['p0trgkv']), g)
        res3 = self.client.get('/trgkvwbjd.json.html')
        self.assertEqual(res3.status_code, http.client.OK)
        self.assertEqual(res3.headers['Content-Type'], 'text/html')

    def test_period_turtle(self):
        res1 = self.client.get('/trgkvwbjd.ttl')
        self.assertEqual(res1.status_code, http.client.OK)
        self.assertEqual(res1.headers['Content-Type'], 'text/turtle')
        self.assertEqual(
            res1.headers['Cache-Control'],
            'public, max-age={}'.format(cache.SHORT_TIME))
        self.assertEqual(
            res1.headers['Content-Disposition'],
            'attachment; filename="periodo-period-trgkvwbjd.ttl"')

        g = Graph().parse(data=res1.get_data(as_text=True), format='turtle')
        self.assertIsNone(
            g.value(predicate=RDF.type, object=SKOS.ConceptScheme))
        self.assertIn((PERIODO['p0trgkvwbjd'],
                       FOAF.isPrimaryTopicOf, HOST['trgkvwbjd.ttl']), g)
        self.assertIn((HOST['trgkvwbjd.ttl'],
                       VOID.inDataset, HOST['d']), g)
        self.assertIn((PERIODO['p0trgkvwbjd'],
                       SKOS.inScheme, PERIODO['p0trgkv']), g)
        res2 = self.client.get('/trgkvwbjd.ttl.html')
        self.assertEqual(res2.status_code, http.client.OK)
        self.assertEqual(res2.headers['Content-Type'], 'text/html')
        self.assertEqual(
            res2.headers['Cache-Control'],
            'public, max-age={}'.format(cache.SHORT_TIME))

    def test_d_turtle(self):
        res1 = self.client.get('/d.ttl')
        self.assertEqual(res1.status_code, http.client.OK)
        self.assertEqual(res1.headers['Content-Type'], 'text/turtle')
        self.assertEqual(
            res1.headers['Cache-Control'],
            'public, max-age={}'.format(cache.SHORT_TIME))
        self.assertEqual(
            res1.headers['Content-Disposition'],
            'attachment; filename="periodo-dataset.ttl"')

        g = Graph().parse(data=res1.get_data(as_text=True), format='turtle')
        self.assertIn((PERIODO['p0d/#authorities'],
                       FOAF.isPrimaryTopicOf, HOST['d.ttl']), g)
        self.assertIn((HOST['d.ttl'],
                       VOID.inDataset, HOST['d']), g)
        self.assertIn((HOST['d'],
                       DCTERMS.provenance, HOST['h#changes']), g)

        res3 = self.client.get('/d.ttl/')
        self.assertEqual(res3.status_code, http.client.NOT_FOUND)

    def test_dataset_turtle(self):
        res1 = self.client.get('/dataset.ttl')
        self.assertEqual(res1.status_code, http.client.OK)
        self.assertEqual(res1.headers['Content-Type'], 'text/turtle')
        self.assertEqual(
            res1.headers['Cache-Control'],
            'public, max-age={}'.format(cache.SHORT_TIME))
        self.assertEqual(
            res1.headers['Content-Disposition'],
            'attachment; filename="periodo-dataset.ttl"')

        g = Graph().parse(data=res1.get_data(as_text=True), format='turtle')
        self.assertIn((PERIODO['p0d/#authorities'],
                       FOAF.isPrimaryTopicOf, HOST['dataset.ttl']), g)
        self.assertIn((HOST['dataset.ttl'],
                       VOID.inDataset, HOST['d']), g)
        self.assertIn((HOST['d'],
                       DCTERMS.provenance, HOST['h#changes']), g)

        res3 = self.client.get('/dataset.ttl/')
        self.assertEqual(res3.status_code, http.client.NOT_FOUND)

    def test_dataset_csv(self):
        res1 = self.client.get('/dataset.csv')
        data = res1.get_data(as_text=True)
        if not res1.status_code == http.client.OK:
            print(data)
        self.assertEqual(res1.status_code, http.client.OK)
        self.assertEqual(res1.headers['Content-Type'], 'text/csv')
        self.assertEqual(
            res1.headers['Cache-Control'],
            'public, max-age={}'.format(cache.MEDIUM_TIME))
        self.assertEqual(
            res1.headers['Content-Disposition'],
            'attachment; filename="periodo-dataset.csv"')

        rows = csv.reader(data.splitlines())
        self.assertEqual(
            next(rows),
            ['period',
             'label',
             'spatial_coverage',
             'gazetteer_links',
             'start',
             'stop',
             'authority',
             'source',
             'publication_year',
             'derived_periods',
             'broader_periods',
             'narrower_periods']
        )
        self.assertEqual(
            next(rows),
            ['http://n2t.net/ark:/99152/p0trgkvkhrv',
             'Iron Age',
             'Spain',
             'http://www.wikidata.org/entity/Q29',
             '-0799',
             '-0549',
             'http://n2t.net/ark:/99152/p0trgkv',
             'The Corinthian, Attic, and Lakonian pottery from Sardis'
             + ' | Schaeffer, Judith Snyder, 1937-'
             + ' | Greenewalt, Crawford H. (Crawford Hallock), 1937-2012.'
             + ' | Ramage, Nancy H., 1942-',
             '1997',
             '',
             'http://n2t.net/ark:/99152/p0trgkv4kxb',
             '']
        )

    def test_h_nt(self):
        with self.client as client:
            res = client.patch(
                '/d/',
                data=self.patch,
                content_type='application/json',
                headers={'Authorization': 'Bearer '
                         + 'NTAwNWViMTgtYmU2Yi00YWMwLWIwODQtMDQ0MzI4OWIzMzc4'})
            res = client.post(
                urlparse(res.headers['Location']).path + 'merge',
                buffered=True,
                headers={'Authorization': 'Bearer '
                         + 'ZjdjNjQ1ODQtMDc1MC00Y2I2LThjODEtMjkzMmY1ZGFhYmI4'})

        res1 = self.client.get('/h.nt')
        self.assertEqual(res1.status_code, http.client.OK)
        self.assertEqual(res1.headers['Content-Type'], 'application/n-triples')
        self.assertEqual(
            res1.headers['X-Accel-Expires'],
            '{}'.format(cache.MEDIUM_TIME))
        self.assertEqual(
            res1.headers['Cache-Control'],
            'public, max-age=0')
        self.assertEqual(
            res1.headers['Content-Disposition'],
            'attachment; filename="periodo-history.nt"')

        g = Graph()
        g.parse(data=res1.get_data(as_text=True), format='nt')
        self.assertIn((HOST['h#patch-1'],
                       FOAF.page, HOST['patches/1/patch.jsonpatch']), g)
        self.assertIn((HOST['d'],
                       DCTERMS.provenance, HOST['h#changes']), g)

        res3 = self.client.get('/h.nt/')
        self.assertEqual(res3.status_code, http.client.NOT_FOUND)

    def test_h_turtle(self):
        res1 = self.client.get('/h.ttl')
        self.assertEqual(res1.status_code, http.client.MOVED_PERMANENTLY)
        self.assertEqual(res1.headers['Location'], str(HOST['h.nt']))

    def test_history_nt(self):
        with self.client as client:
            res = client.patch(
                '/d/',
                data=self.patch,
                content_type='application/json',
                headers={'Authorization': 'Bearer '
                         + 'NTAwNWViMTgtYmU2Yi00YWMwLWIwODQtMDQ0MzI4OWIzMzc4'})
            res = client.post(
                urlparse(res.headers['Location']).path + 'merge',
                buffered=True,
                headers={'Authorization': 'Bearer '
                         + 'ZjdjNjQ1ODQtMDc1MC00Y2I2LThjODEtMjkzMmY1ZGFhYmI4'})

        res1 = self.client.get('/history.nt')
        self.assertEqual(res1.status_code, http.client.OK)
        self.assertEqual(res1.headers['Content-Type'], 'application/n-triples')
        self.assertEqual(
            res1.headers['X-Accel-Expires'],
            '{}'.format(cache.MEDIUM_TIME))
        self.assertEqual(
            res1.headers['Cache-Control'],
            'public, max-age=0')
        self.assertEqual(
            res1.headers['Content-Disposition'],
            'attachment; filename="periodo-history.nt"')

        g = Graph()
        g.parse(data=res1.get_data(as_text=True), format='turtle')
        self.assertIn((HOST['h#patch-1'],
                       FOAF.page, HOST['patches/1/patch.jsonpatch']), g)
        self.assertIn((HOST['d'],
                       DCTERMS.provenance, HOST['h#changes']), g)

        res3 = self.client.get('/history.nt/')
        self.assertEqual(res3.status_code, http.client.NOT_FOUND)

    def test_history_json(self):
        res1 = self.client.get('/history.json')
        self.assertEqual(res1.status_code, http.client.NOT_FOUND)

    def test_export(self):
        res1 = self.client.get('/export.sql')
        self.assertEqual(res1.status_code, http.client.OK)
        self.assertEqual(res1.headers['Content-Type'], 'text/plain')
