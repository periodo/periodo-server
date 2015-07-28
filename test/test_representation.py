import os
import tempfile
import unittest
import http.client
from rdflib import Graph, URIRef
from rdflib.plugins import sparql
from rdflib.namespace import Namespace, RDF, DCTERMS, OWL
from urllib.parse import urlparse
from flask.ext.principal import ActionNeed
from .filepath import filepath
from periodo import app, commands, database, auth

VOID = Namespace('http://rdfs.org/ns/void#')
SKOS = Namespace('http://www.w3.org/2004/02/skos/core#')
PERIODO = Namespace('http://n2t.net/ark:/99152/')
FOAF = Namespace('http://xmlns.com/foaf/0.1/')


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

    def test_vocab(self):
        res1 = self.client.get('/v', buffered=True)
        self.assertEqual(res1.status_code, http.client.OK)
        self.assertEqual(res1.headers['Content-Type'],
                         'text/turtle; charset=utf-8')

        g = Graph()
        g.parse(format='turtle', data=res1.get_data(as_text=True))
        self.assertIn(
            (PERIODO['p0v#spatialCoverageDescription'],
             RDF.type, OWL.DatatypeProperty), g)
        self.assertIn(
            (PERIODO['p0v#earliestYear'],
             RDF.type, OWL.DatatypeProperty), g)
        self.assertIn(
            (PERIODO['p0v#latestYear'],
             RDF.type, OWL.DatatypeProperty), g)

    def test_dataset_description(self):
        res1 = self.client.get(
            '/', headers={'Accept': 'text/html'}, buffered=True)
        self.assertIn(
            res1.status_code, (http.client.OK, http.client.NOT_ACCEPTABLE))
        self.assertEqual(res1.headers['Content-Type'], 'text/html')

        res2 = self.client.get('/', headers={'Accept': 'text/turtle'})
        self.assertEqual(res2.status_code, http.client.OK)
        self.assertEqual(res2.headers['Content-Type'], 'text/turtle')

        res3 = self.client.get('/.well-known/void')
        self.assertEqual(res2.status_code, http.client.OK)
        self.assertEqual(res2.headers['Content-Type'], 'text/turtle')
        self.assertEqual(res2.get_data(as_text=True),
                         res3.get_data(as_text=True))

        g = Graph()
        g.parse(format='turtle', data=res2.get_data(as_text=True))
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
        self.assertEqual(concept_count, 1)
        scheme_count = next(iter(g.query(
            q, initBindings={'class': SKOS.ConceptScheme})))['count'].value
        self.assertEqual(scheme_count, 1)

    def test_add_contributors_to_dataset_description(self):
        contribution = (URIRef('http://n2t.net/ark:/99152/p0d'),
                        DCTERMS.contributor,
                        URIRef('http://orcid.org/1234-5678-9101-112X'))
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

    def test_dataset_data(self):
        res1 = self.client.get('/d/')
        self.assertEqual(res1.status_code, http.client.OK)
        self.assertEqual(res1.headers['Content-Type'], 'application/json')
        res2 = self.client.get('/d.json')
        self.assertEqual(res2.status_code, http.client.OK)
        self.assertEqual(res2.headers['Content-Type'], 'application/json')
        res3 = self.client.get('/d.jsonld')
        self.assertEqual(res3.status_code, http.client.OK)
        self.assertEqual(res3.headers['Content-Type'], 'application/ld+json')
        res4 = self.client.get('/d/', headers={'Accept': 'application/ld+json'})
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
        g = Graph().parse(data=res4.get_data(as_text=True), format='json-ld')
        self.assertIn((PERIODO['p0d/#periodCollections'],
                       FOAF.isPrimaryTopicOf, PERIODO['p0d/']), g)
        self.assertIn((PERIODO['p0d/'],
                       VOID.inDataset, PERIODO['p0d']), g)

    def test_period_collection(self):
        res1 = self.client.get('/trgkv')
        self.assertEqual(res1.status_code, http.client.SEE_OTHER)
        self.assertEqual(urlparse(res1.headers['Location']).path, '/')
        self.assertEqual(urlparse(res1.headers['Location']).fragment, 'trgkv')
        res2 = self.client.get('/trgkv', headers={'Accept': 'application/json'})
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
        self.assertEqual(urlparse(res1.headers['Location']).fragment, 'trgkv')
        res5 = self.client.get('/trgkv/')
        self.assertEqual(res5.status_code, http.client.NOT_FOUND)

    def test_period_collection_data(self):
        res1 = self.client.get('/trgkv.json')
        self.assertEqual(res1.status_code, http.client.OK)
        self.assertEqual(res1.headers['Content-Type'], 'application/json')
        res2 = self.client.get('/trgkv.jsonld')
        self.assertEqual(res2.status_code, http.client.OK)
        self.assertEqual(res2.headers['Content-Type'], 'application/ld+json')
        g = Graph().parse(data=res2.get_data(as_text=True), format='json-ld')
        self.assertIsNone(g.value(predicate=RDF.type, object=RDF.Bag))
        self.assertIn((PERIODO['p0trgkv'],
                       FOAF.isPrimaryTopicOf, PERIODO['p0trgkv.jsonld']), g)
        self.assertIn((PERIODO['p0trgkv.jsonld'],
                       VOID.inDataset, PERIODO['p0d']), g)
        res3 = self.client.get('/trgkv.json/')
        self.assertEqual(res3.status_code, http.client.NOT_FOUND)
        res4 = self.client.get('/trgkv.jsonld/')
        self.assertEqual(res4.status_code, http.client.NOT_FOUND)

    def test_period_definition(self):
        res1 = self.client.get('/trgkvwbjd')
        self.assertEqual(res1.status_code, http.client.SEE_OTHER)
        self.assertEqual(urlparse(res1.headers['Location']).path, '/')
        self.assertEqual(
            urlparse(res1.headers['Location']).fragment, 'trgkvwbjd')
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
        self.assertEqual(
            urlparse(res1.headers['Location']).fragment, 'trgkvwbjd')

    def test_period_definition_data(self):
        res1 = self.client.get('/trgkvwbjd.json')
        self.assertEqual(res1.status_code, http.client.OK)
        self.assertEqual(res1.headers['Content-Type'], 'application/json')
        res2 = self.client.get('/trgkvwbjd.jsonld')
        self.assertEqual(res2.status_code, http.client.OK)
        self.assertEqual(res2.headers['Content-Type'], 'application/ld+json')
        g = Graph().parse(data=res1.get_data(as_text=True), format='json-ld')
        self.assertIsNone(
            g.value(predicate=RDF.type, object=SKOS.ConceptScheme))
        self.assertIn((PERIODO['p0trgkvwbjd'],
                       FOAF.isPrimaryTopicOf, PERIODO['p0trgkvwbjd.json']), g)
        self.assertIn((PERIODO['p0trgkvwbjd.json'],
                       VOID.inDataset, PERIODO['p0d']), g)
        self.assertIn((PERIODO['p0trgkvwbjd'],
                       SKOS.inScheme, PERIODO['p0trgkv']), g)
