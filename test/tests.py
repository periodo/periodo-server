import os
import json
import periodo
import identifier
import tempfile
import unittest
import http.client
from rdflib import Graph, URIRef
from rdflib.plugins import sparql
from rdflib.namespace import Namespace, RDF, DCTERMS, OWL
from urllib.parse import urlparse
from flask.ext.principal import ActionNeed
from jsonpatch import JsonPatch

def setUpModule():
    os.chdir('test')

VOID = Namespace('http://rdfs.org/ns/void#')
SKOS = Namespace('http://www.w3.org/2004/02/skos/core#')
PERIODO = Namespace('http://n2t.net/ark:/99152/')
FOAF = Namespace('http://xmlns.com/foaf/0.1/')

class TestAuthentication(unittest.TestCase):

    def setUp(self):
        self.db_fd, periodo.app.config['DATABASE'] = tempfile.mkstemp()
        periodo.app.config['TESTING'] = True
        self.app = periodo.app.test_client()
        periodo.init_db()
        self.identity = periodo.add_user_or_update_credentials({
            'name': 'Testy Testerson',
            'access_token': '5005eb18-be6b-4ac0-b084-0443289b3378',
            'expires_in': 631138518,
            'orcid': '1234-5678-9101-112X',
        })
        self.expired_identity = periodo.add_user_or_update_credentials({
            'name': 'Eric Expired',
            'access_token': 'f7c64584-0750-4cb6-8c81-2932f5daabb8',
            'expires_in': -3600,
            'orcid': '1211-1098-7654-321X',
        })

    def tearDown(self):
        os.close(self.db_fd)
        os.unlink(periodo.app.config['DATABASE'])

    def test_add_user(self):
        self.assertEqual(
            self.identity.id, 'http://orcid.org/1234-5678-9101-112X')
        self.assertEqual(
            self.identity.auth_type, 'bearer')
        with periodo.app.app_context():
            row = periodo.query_db(
                'SELECT name, permissions, b64token FROM user WHERE id = ?',
                (self.identity.id,), one=True)
            self.assertEqual(row['name'], 'Testy Testerson')
            self.assertEqual(row['permissions'], '[["action", "submit-patch"]]')
            self.assertEqual(row['b64token'], b'NTAwNWViMTgtYmU2Yi00YWMwLWIwODQtMDQ0MzI4OWIzMzc4')

    def test_add_expired_user(self):
        self.assertIsNone(self.expired_identity.id)
        self.assertIsNone(self.expired_identity.auth_type)

    def test_no_credentials(self):
        res = self.app.patch('/d/')
        self.assertEqual(res.status_code, http.client.UNAUTHORIZED)
        self.assertEqual(
            res.headers['WWW-Authenticate'],
            'Bearer realm="PeriodO"')

    def test_unsupported_auth_method(self):
        res = self.app.patch(
            '/d/',
            headers={ 'Authorization': 'Basic QWxhZGRpbjpvcGVuIHNlc2FtZQ==' } )
        self.assertEqual(res.status_code, http.client.UNAUTHORIZED)
        self.assertEqual(
            res.headers['WWW-Authenticate'],
            'Bearer realm="PeriodO"')

    def test_malformed_token(self):
        res = self.app.patch(
            '/d/',
            headers={ 'Authorization': 'Bearer =!@#$%^&*()_+' } )
        self.assertEqual(res.status_code, http.client.UNAUTHORIZED)
        self.assertEqual(
            res.headers['WWW-Authenticate'],
            'Bearer realm="PeriodO", error="invalid_token", '
            + 'error_description="The access token is malformed", '
            + 'error_uri="http://tools.ietf.org/html/rfc6750#section-6.2.2"')

    def test_token_not_in_database(self):
        res = self.app.patch(
            '/d/',
            headers={ 'Authorization': 'Bearer mF_9.B5f-4.1JqM' } )
        self.assertEqual(res.status_code, http.client.UNAUTHORIZED)
        self.assertEqual(
            res.headers['WWW-Authenticate'],
            'Bearer realm="PeriodO", error="invalid_token", '
            + 'error_description="The access token is invalid", '
            + 'error_uri="http://tools.ietf.org/html/rfc6750#section-6.2.2"')

    def test_expired_token(self):
        res = self.app.patch(
            '/d/',
            headers={ 'Authorization': 'Bearer ZjdjNjQ1ODQtMDc1MC00Y2I2LThjODEtMjkzMmY1ZGFhYmI4' } )
        self.assertEqual(res.status_code, http.client.UNAUTHORIZED)
        self.assertEqual(
            res.headers['WWW-Authenticate'],
            'Bearer realm="PeriodO", error="invalid_token", '
            + 'error_description="The access token expired", '
            + 'error_uri="http://tools.ietf.org/html/rfc6750#section-6.2.2"')

class TestAuthorization(unittest.TestCase):

    def setUp(self):
        self.db_fd, periodo.app.config['DATABASE'] = tempfile.mkstemp()
        periodo.app.config['TESTING'] = True
        self.app = periodo.app.test_client()
        periodo.init_db()
        periodo.load_data('test-data.json')
        self.unauthorized_identity = periodo.add_user_or_update_credentials({
            'name': 'Dangerous Dan',
            'access_token': 'f7e00c02-6f97-4636-8499-037446d95446',
            'expires_in': 631138518,
            'orcid': '0000-0000-0000-000X',
        })
        with periodo.app.app_context():
            db = periodo.get_db()
            curs = db.cursor()
            curs.execute('UPDATE user SET permissions = ? WHERE name = ?',
                         ('[]', 'Dangerous Dan'))
            db.commit()
        self.user_identity = periodo.add_user_or_update_credentials({
            'name': 'Regular Gal',
            'access_token': '5005eb18-be6b-4ac0-b084-0443289b3378',
            'expires_in': 631138518,
            'orcid': '1234-5678-9101-112X',
        })
        self.admin_identity = periodo.add_user_or_update_credentials({
            'name': 'Super Admin',
            'access_token': 'f7c64584-0750-4cb6-8c81-2932f5daabb8',
            'expires_in': 3600,
            'orcid': '1211-1098-7654-321X',
        }, (ActionNeed('accept-patch'),))
        with open('test-patch-replace-values-1.json') as f:
            self.patch = f.read()

    def tearDown(self):
        os.close(self.db_fd)
        os.unlink(periodo.app.config['DATABASE'])

    def test_add_admin_user(self):
        with periodo.app.app_context():
            row = periodo.query_db(
                'SELECT permissions FROM user WHERE id = ?',
                (self.admin_identity.id,), one=True)
            self.assertEqual(
                row['permissions'],
                '[["action", "submit-patch"], ["action", "accept-patch"]]')

    def test_unauthorized_user(self):
        res = self.app.patch(
            '/d/',
            headers={ 'Authorization': 'Bearer ZjdlMDBjMDItNmY5Ny00NjM2LTg0OTktMDM3NDQ2ZDk1NDQ2' } )
        self.assertEqual(res.status_code, http.client.FORBIDDEN)
        self.assertEqual(
            res.headers['WWW-Authenticate'],
            'Bearer realm="PeriodO", error="insufficient_scope", '
            + 'error_description="The access token does not provide sufficient privileges", '
            + 'error_uri="http://tools.ietf.org/html/rfc6750#section-6.2.3"')

    def test_authorized_user(self):
        with self.app as client:
            res = client.patch(
                '/d/',
                data=self.patch,
                content_type='application/json',
                headers={ 'Authorization': 'Bearer NTAwNWViMTgtYmU2Yi00YWMwLWIwODQtMDQ0MzI4OWIzMzc4' } )
            self.assertEqual(res.status_code, http.client.ACCEPTED)
            patch_id = int(res.headers['Location'].split('/')[-2])
            creator = periodo.query_db(
                'SELECT created_by FROM patch_request WHERE id = ?',
                (patch_id,), one=True)['created_by']
            self.assertEqual(creator, 'http://orcid.org/1234-5678-9101-112X')

    def test_nonadmin_merge(self):
        res = self.app.patch(
            '/d/',
            data=self.patch,
            content_type='application/json',
            headers={ 'Authorization': 'Bearer NTAwNWViMTgtYmU2Yi00YWMwLWIwODQtMDQ0MzI4OWIzMzc4' } )
        res = self.app.post(
            urlparse(res.headers['Location']).path + 'merge',
            headers={ 'Authorization': 'Bearer NTAwNWViMTgtYmU2Yi00YWMwLWIwODQtMDQ0MzI4OWIzMzc4' } )
        self.assertEqual(res.status_code, http.client.FORBIDDEN)
        self.assertEqual(
            res.headers['WWW-Authenticate'],
            'Bearer realm="PeriodO", error="insufficient_scope", '
            + 'error_description="The access token does not provide sufficient privileges", '
            + 'error_uri="http://tools.ietf.org/html/rfc6750#section-6.2.3"')

    def test_admin_merge(self):
        with self.app as client:
            res = client.patch(
                '/d/',
                data=self.patch,
                content_type='application/json',
                headers={ 'Authorization': 'Bearer NTAwNWViMTgtYmU2Yi00YWMwLWIwODQtMDQ0MzI4OWIzMzc4' } )
            patch_id = int(res.headers['Location'].split('/')[-2])
            res = client.post(
                urlparse(res.headers['Location']).path + 'merge',
                headers={ 'Authorization': 'Bearer ZjdjNjQ1ODQtMDc1MC00Y2I2LThjODEtMjkzMmY1ZGFhYmI4' } )
            self.assertEqual(res.status_code, http.client.NO_CONTENT)
            merger = periodo.query_db(
                'SELECT merged_by FROM patch_request WHERE id = ?',
                (patch_id,), one=True)['merged_by']
            self.assertEqual(merger, 'http://orcid.org/1211-1098-7654-321X')

    def test_noncreator_patch_update(self):
        res = self.app.patch(
            '/d/',
            data=self.patch,
            content_type='application/json',
            headers={ 'Authorization': 'Bearer NTAwNWViMTgtYmU2Yi00YWMwLWIwODQtMDQ0MzI4OWIzMzc4' } )
        res = self.app.put(
            urlparse(res.headers['Location']).path + 'patch.jsonpatch',
            data=self.patch,
            content_type='application/json',
            headers={ 'Authorization': 'Bearer ZjdjNjQ1ODQtMDc1MC00Y2I2LThjODEtMjkzMmY1ZGFhYmI4' } )
        self.assertEqual(res.status_code, http.client.FORBIDDEN)
        self.assertEqual(
            res.headers['WWW-Authenticate'],
            'Bearer realm="PeriodO", error="insufficient_scope", '
            + 'error_description="The access token does not provide sufficient privileges", '
            + 'error_uri="http://tools.ietf.org/html/rfc6750#section-6.2.3"')

    def test_creator_patch_update(self):
        with self.app as client:
            res = client.patch(
                '/d/',
                data=self.patch,
                content_type='application/json',
                headers={ 'Authorization': 'Bearer NTAwNWViMTgtYmU2Yi00YWMwLWIwODQtMDQ0MzI4OWIzMzc4' } )
            res = client.put(
                urlparse(res.headers['Location']).path + 'patch.jsonpatch',
                data=self.patch,
                content_type='application/json',
                headers={ 'Authorization': 'Bearer NTAwNWViMTgtYmU2Yi00YWMwLWIwODQtMDQ0MzI4OWIzMzc4' } )
            self.assertEqual(res.status_code, http.client.OK)

    def test_update_merged_patch(self):
        with self.app as client:
            res = client.patch(
                '/d/',
                data=self.patch,
                content_type='application/json',
                headers={ 'Authorization': 'Bearer NTAwNWViMTgtYmU2Yi00YWMwLWIwODQtMDQ0MzI4OWIzMzc4' } )
            patch_path = urlparse(res.headers['Location']).path
            res = client.post(
                patch_path + 'merge',
                headers={ 'Authorization': 'Bearer ZjdjNjQ1ODQtMDc1MC00Y2I2LThjODEtMjkzMmY1ZGFhYmI4' } )
            res = client.put(
                patch_path + 'patch.jsonpatch',
                data=self.patch,
                content_type='application/json',
                headers={ 'Authorization': 'Bearer NTAwNWViMTgtYmU2Yi00YWMwLWIwODQtMDQ0MzI4OWIzMzc4' } )
        self.assertEqual(res.status_code, http.client.FORBIDDEN)
        self.assertEqual(
            res.headers['WWW-Authenticate'],
            'Bearer realm="PeriodO", error="insufficient_scope", '
            + 'error_description="The access token does not provide sufficient privileges", '
            + 'error_uri="http://tools.ietf.org/html/rfc6750#section-6.2.3"')

class TestPatchMethods(unittest.TestCase):

    def setUp(self):
        self.db_fd, periodo.app.config['DATABASE'] = tempfile.mkstemp()
        periodo.app.config['TESTING'] = True
        self.app = periodo.app.test_client()
        periodo.init_db()
        periodo.load_data('test-data.json')
        self.user_identity = periodo.add_user_or_update_credentials({
            'name': 'Regular Gal',
            'access_token': '5005eb18-be6b-4ac0-b084-0443289b3378',
            'expires_in': 631138518,
            'orcid': '1234-5678-9101-112X',
        })
        with open('test-patch-replace-values-1.json') as f:
            self.patch = f.read()

    def tearDown(self):
        os.close(self.db_fd)
        os.unlink(periodo.app.config['DATABASE'])

    def test_update_patch(self):
        res = self.app.patch(
            '/d/',
            data=self.patch,
            content_type='application/json',
            headers={ 'Authorization': 'Bearer NTAwNWViMTgtYmU2Yi00YWMwLWIwODQtMDQ0MzI4OWIzMzc4' } )
        patch_url = urlparse(res.headers['Location']).path + 'patch.jsonpatch'
        res = self.app.get(patch_url)
        res = self.app.get(patch_url)
        self.assertEqual(json.loads(self.patch),
                         json.loads(res.get_data(as_text=True)))
        with open('test-patch-replace-values-2.json') as f:
            self.patch2 = f.read()
        res = self.app.put(
            patch_url,
            data=self.patch2,
            content_type='application/json',
            headers={ 'Authorization': 'Bearer NTAwNWViMTgtYmU2Yi00YWMwLWIwODQtMDQ0MzI4OWIzMzc4' } )
        self.assertEqual(res.status_code, http.client.OK)
        res = self.app.get(patch_url)
        res = self.app.get(patch_url)
        self.assertEqual(json.loads(self.patch2),
                         json.loads(res.get_data(as_text=True)))

class TestRepresentationsAndRedirects(unittest.TestCase):

    def setUp(self):
        self.db_fd, periodo.app.config['DATABASE'] = tempfile.mkstemp()
        periodo.app.config['TESTING'] = True
        self.app = periodo.app.test_client()
        periodo.init_db()
        periodo.load_data('test-data.json')
        self.user_identity = periodo.add_user_or_update_credentials({
            'name': 'Regular Gal',
            'access_token': '5005eb18-be6b-4ac0-b084-0443289b3378',
            'expires_in': 631138518,
            'orcid': '1234-5678-9101-112X',
        })
        self.admin_identity = periodo.add_user_or_update_credentials({
            'name': 'Super Admin',
            'access_token': 'f7c64584-0750-4cb6-8c81-2932f5daabb8',
            'expires_in': 3600,
            'orcid': '1211-1098-7654-321X',
        }, (ActionNeed('accept-patch'),))
        with open('test-patch-replace-values-1.json') as f:
            self.patch = f.read()

    def tearDown(self):
        os.close(self.db_fd)
        os.unlink(periodo.app.config['DATABASE'])

    def test_vocab(self):
        res1 = self.app.get('/v', buffered=True)
        self.assertEqual(res1.status_code, http.client.OK)
        self.assertEqual(res1.headers['Content-Type'], 'text/turtle; charset=utf-8')

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
        res1 = self.app.get('/', headers={ 'Accept': 'text/html' }, buffered=True)
        self.assertIn(res1.status_code, (http.client.OK, http.client.NOT_ACCEPTABLE))
        self.assertEqual(res1.headers['Content-Type'], 'text/html')

        res2 = self.app.get('/', headers={ 'Accept': 'text/turtle' })
        self.assertEqual(res2.status_code, http.client.OK)
        self.assertEqual(res2.headers['Content-Type'], 'text/turtle')

        res3 = self.app.get('/.well-known/void')
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
        q = sparql.prepareQuery(
'''
SELECT ?count 
WHERE { 
  ?d void:classPartition ?p .
  ?p void:class ?class .
  ?p void:entities ?count .
}
''', initNs = { 'void': VOID, 'skos': SKOS })
        concept_count = next(iter(g.query(
            q, initBindings = { 'class': SKOS.Concept  })))['count'].value
        self.assertEqual(concept_count, 1)
        scheme_count = next(iter(g.query(
            q, initBindings = { 'class': SKOS.ConceptScheme  })))['count'].value
        self.assertEqual(scheme_count, 1)

    def test_add_contributors_to_dataset_description(self):
        contribution = (URIRef('http://n2t.net/ark:/99152/p0d'),
                        DCTERMS.contributor,
                        URIRef('http://orcid.org/1234-5678-9101-112X'))
        data = self.app.get(
            '/', headers={ 'Accept': 'text/turtle' }).get_data(as_text=True)
        g = Graph().parse(format='turtle', data=data)
        self.assertNotIn(contribution, g)
        with self.app as client:
            res = client.patch(
                '/d/',
                data=self.patch,
                content_type='application/json',
                headers={ 'Authorization': 'Bearer NTAwNWViMTgtYmU2Yi00YWMwLWIwODQtMDQ0MzI4OWIzMzc4' } )
            patch_id = int(res.headers['Location'].split('/')[-2])
            res = client.post(
                urlparse(res.headers['Location']).path + 'merge',
                headers={ 'Authorization': 'Bearer ZjdjNjQ1ODQtMDc1MC00Y2I2LThjODEtMjkzMmY1ZGFhYmI4' } )
        data = self.app.get(
            '/', headers={ 'Accept': 'text/turtle' }).get_data(as_text=True)
        g = Graph().parse(format='turtle', data=data)
        self.assertIn(contribution, g)

    def test_dataset(self):
        res = self.app.get('/d')
        self.assertEqual(res.status_code, http.client.SEE_OTHER)
        self.assertEqual(urlparse(res.headers['Location']).path, '/d/')

    def test_dataset_data(self):
        res1 = self.app.get('/d/')
        self.assertEqual(res1.status_code, http.client.OK)
        self.assertEqual(res1.headers['Content-Type'], 'application/json')
        res2 = self.app.get('/d.json')
        self.assertEqual(res2.status_code, http.client.OK)
        self.assertEqual(res2.headers['Content-Type'], 'application/json')
        res3 = self.app.get('/d.jsonld')
        self.assertEqual(res3.status_code, http.client.OK)
        self.assertEqual(res3.headers['Content-Type'], 'application/ld+json')
        res4 = self.app.get('/d/', headers={ 'Accept': 'application/ld+json' })
        self.assertEqual(res4.status_code, http.client.OK)
        self.assertEqual(res4.headers['Content-Type'], 'application/ld+json')
        g = Graph().parse(data=res4.get_data(as_text=True), format='json-ld')
        self.assertIn((PERIODO['p0d/#periodCollections'],
                       FOAF.isPrimaryTopicOf, PERIODO['p0d/']), g)
        self.assertIn((PERIODO['p0d/'],
                       VOID.inDataset, PERIODO['p0d']), g)

    def test_period_collection(self):
        res1 = self.app.get('/trgkv')
        self.assertEqual(res1.status_code, http.client.SEE_OTHER)
        self.assertEqual(urlparse(res1.headers['Location']).path, '/')
        self.assertEqual(urlparse(res1.headers['Location']).fragment, 'trgkv')
        res2 = self.app.get('/trgkv', headers={'Accept':'application/json'})
        self.assertEqual(res2.status_code, http.client.SEE_OTHER)
        self.assertEqual(urlparse(res2.headers['Location']).path, '/trgkv.json')
        res3 = self.app.get('/trgkv', headers={'Accept':'application/ld+json'})
        self.assertEqual(res3.status_code, http.client.SEE_OTHER)
        self.assertEqual(urlparse(res3.headers['Location']).path, '/trgkv.jsonld')
        res4 = self.app.get('/trgkv', headers={'Accept':'text/html'})
        self.assertEqual(res4.status_code, http.client.SEE_OTHER)
        self.assertEqual(urlparse(res4.headers['Location']).path, '/')
        self.assertEqual(urlparse(res1.headers['Location']).fragment, 'trgkv')
        res5 = self.app.get('/trgkv/')
        self.assertEqual(res5.status_code, http.client.NOT_FOUND)

    def test_period_collection_data(self):
        res1 = self.app.get('/trgkv.json')
        self.assertEqual(res1.status_code, http.client.OK)
        self.assertEqual(res1.headers['Content-Type'], 'application/json')
        res2 = self.app.get('/trgkv.jsonld')
        self.assertEqual(res2.status_code, http.client.OK)
        self.assertEqual(res2.headers['Content-Type'], 'application/ld+json')
        g = Graph().parse(data=res2.get_data(as_text=True), format='json-ld')
        self.assertIsNone(g.value(predicate=RDF.type, object=RDF.Bag))
        self.assertIn((PERIODO['p0trgkv'],
                       FOAF.isPrimaryTopicOf, PERIODO['p0trgkv.jsonld']), g)
        self.assertIn((PERIODO['p0trgkv.jsonld'],
                       VOID.inDataset, PERIODO['p0d']), g)
        res3 = self.app.get('/trgkv.json/')
        self.assertEqual(res3.status_code, http.client.NOT_FOUND)
        res4 = self.app.get('/trgkv.jsonld/')
        self.assertEqual(res4.status_code, http.client.NOT_FOUND)

    def test_period_definition(self):
        res1 = self.app.get('/trgkvwbjd')
        self.assertEqual(res1.status_code, http.client.SEE_OTHER)
        self.assertEqual(urlparse(res1.headers['Location']).path, '/')
        self.assertEqual(urlparse(res1.headers['Location']).fragment, 'trgkvwbjd')
        res2 = self.app.get('/trgkvwbjd', headers={'Accept':'application/json'})
        self.assertEqual(res2.status_code, http.client.SEE_OTHER)
        self.assertEqual(urlparse(res2.headers['Location']).path, '/trgkvwbjd.json')
        res3 = self.app.get('/trgkvwbjd', headers={'Accept':'application/ld+json'})
        self.assertEqual(res3.status_code, http.client.SEE_OTHER)
        self.assertEqual(urlparse(res3.headers['Location']).path, '/trgkvwbjd.jsonld')
        res4 = self.app.get('/trgkvwbjd', headers={'Accept':'text/html'})
        self.assertEqual(res4.status_code, http.client.SEE_OTHER)
        self.assertEqual(urlparse(res4.headers['Location']).path, '/')
        self.assertEqual(urlparse(res1.headers['Location']).fragment, 'trgkvwbjd')

    def test_period_definition_data(self):
        res1 = self.app.get('/trgkvwbjd.json')
        self.assertEqual(res1.status_code, http.client.OK)
        self.assertEqual(res1.headers['Content-Type'], 'application/json')
        res2 = self.app.get('/trgkvwbjd.jsonld')
        self.assertEqual(res2.status_code, http.client.OK)
        self.assertEqual(res2.headers['Content-Type'], 'application/ld+json')
        g = Graph().parse(data=res1.get_data(as_text=True), format='json-ld')
        self.assertIsNone(g.value(predicate=RDF.type, object=SKOS.ConceptScheme))
        self.assertIn((PERIODO['p0trgkvwbjd'],
                       FOAF.isPrimaryTopicOf, PERIODO['p0trgkvwbjd.json']), g)
        self.assertIn((PERIODO['p0trgkvwbjd.json'],
                       VOID.inDataset, PERIODO['p0d']), g)

class TestIdentifiers(unittest.TestCase):

    def test_substitution_error(self):
        def substitute(s):
            chars = list(s)
            chars[2] = identifier.XDIGITS[
                (identifier.XDIGITS.index(chars[2]) + 1)
                % len(identifier.XDIGITS)]
            return ''.join(chars)

        cid = identifier.for_collection()
        identifier.check(cid)
        cid2 = substitute(cid)
        with self.assertRaises(identifier.IdentifierException):
            identifier.check(cid2)

        did = identifier.for_definition(cid)
        identifier.check(did)
        did2 = substitute(did)
        with self.assertRaises(identifier.IdentifierException):
            identifier.check(did2)

    def test_transposition_error(self):
        def transpose(s):
            chars = list(s)
            for i in range(-3, -(len(s)+1), -1):
                if not chars[i] == chars[i+1]:
                    chars[i], chars[i+1] = chars[i+1], chars[i]
                    return ''.join(chars)

        cid = identifier.for_collection()
        identifier.check(cid)
        cid2 = transpose(cid)
        with self.assertRaises(identifier.IdentifierException):
            identifier.check(cid2)

        did = identifier.for_definition(cid)
        identifier.check(did)
        did2 = transpose(did)
        with self.assertRaises(identifier.IdentifierException):
            identifier.check(did2)

    def test_id_has_wrong_shape(self):
        with self.assertRaises(identifier.IdentifierException):
            identifier.check('p06rw8') # collection id too short
        with self.assertRaises(identifier.IdentifierException):
            identifier.check('p06rw87/669p') # definition id has slash

    def test_generate_definition_id(self):
        cid = identifier.for_collection()
        did = identifier.for_definition(cid)
        self.assertTrue(did.startswith(cid))
        self.assertEqual(len(did), 11)

    def test_replace_skolem_ids_when_adding_items(self):
        with open('test-data.json') as f:
            data = json.load(f)
        with open('test-patch-adds-items.json') as f:
            original_patch = JsonPatch(json.load(f))
        applied_patch = identifier.replace_skolem_ids(original_patch, data)
        self.assertRegex(
            applied_patch.patch[0]['path'],
            r'^/periodCollections/p0trgkv/definitions/p0trgkv[%s]{4}$' % identifier.XDIGITS)
        self.assertRegex(
            applied_patch.patch[0]['value']['id'],
            r'^p0trgkv[%s]{4}$' % identifier.XDIGITS)
        identifier.check(applied_patch.patch[0]['value']['id'])

        self.assertRegex(
            applied_patch.patch[1]['path'],
            r'^/periodCollections/p0[%s]{5}$' % identifier.XDIGITS)
        self.assertRegex(
            applied_patch.patch[1]['value']['id'],
            r'^p0[%s]{5}$' % identifier.XDIGITS)
        collection_id = applied_patch.patch[1]['value']['id']
        identifier.check(collection_id)
        self.assertRegex(
            list(applied_patch.patch[1]['value']['definitions'].keys())[0],
            r'^%s[%s]{4}$' % (collection_id, identifier.XDIGITS))
        self.assertEqual(
            list(applied_patch.patch[1]['value']['definitions'].values())[0]['id'],
            list(applied_patch.patch[1]['value']['definitions'].keys())[0])
        identifier.check(list(applied_patch.patch[1]['value']['definitions'].keys())[0])

    def test_replace_skolem_ids_when_replacing_definitions(self):
        with open('test-data.json') as f:
            data = json.load(f)
        with open('test-patch-replaces-definitions.json') as f:
            original_patch = JsonPatch(json.load(f))
        applied_patch = identifier.replace_skolem_ids(original_patch, data)
        self.assertEqual(
            applied_patch.patch[0]['path'],
            original_patch.patch[0]['path'])
        definition_id, definition = list(applied_patch.patch[0]['value'].items())[0]
        self.assertRegex(
            definition_id,
            r'^p0trgkv[%s]{4}$' % identifier.XDIGITS)
        self.assertEqual(definition_id, definition['id'])
        identifier.check(definition_id)

    def test_replace_skolem_ids_when_replacing_collections(self):
        with open('test-data.json') as f:
            data = json.load(f)
        with open('test-patch-replaces-collections.json') as f:
            original_patch = JsonPatch(json.load(f))
        applied_patch = identifier.replace_skolem_ids(original_patch, data)
        self.assertEqual(
            applied_patch.patch[0]['path'],
            original_patch.patch[0]['path'])

        collection_id, collection = list(applied_patch.patch[0]['value'].items())[0]
        self.assertRegex(
            collection_id,
            r'^p0[%s]{5}$' % identifier.XDIGITS)
        self.assertEqual(collection_id, collection['id'])
        identifier.check(collection_id)

        definition_id, definition = list(applied_patch.patch[0]['value'][collection_id]['definitions'].items())[0]
        self.assertRegex(
            definition_id,
            r'^%s[%s]{4}$' % (collection_id, identifier.XDIGITS))
        self.assertEqual(definition_id, definition['id'])
        identifier.check(definition_id)
