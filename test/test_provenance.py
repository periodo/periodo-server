import os
import tempfile
import unittest
import http.client
from rdflib import ConjunctiveGraph, URIRef
from rdflib.namespace import Namespace, XSD, RDFS
from urllib.parse import urlparse
from flask_principal import ActionNeed
from .filepath import filepath
from periodo import app, database, commands, auth

VOID = Namespace('http://rdfs.org/ns/void#')
SKOS = Namespace('http://www.w3.org/2004/02/skos/core#')
PERIODO = Namespace('http://n2t.net/ark:/99152/')
FOAF = Namespace('http://xmlns.com/foaf/0.1/')
PROV = Namespace('http://www.w3.org/ns/prov#')
HOST = Namespace('http://localhost:5000/')

W3CDTF = r'^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}\+00.00$'


class TestProvenance(unittest.TestCase):

    def setUp(self):
        self.db_fd, app.config['DATABASE'] = tempfile.mkstemp()
        app.config['TESTING'] = True
        self.client = app.test_client()
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

    def test_get_history(self):
        with open(filepath('test-patch-adds-items.json')) as f:
            patch = f.read()

        with self.client as client:
            res1 = client.patch(
                '/d/',
                data=patch,
                content_type='application/json',
                headers={'Authorization': 'Bearer '
                         + 'NTAwNWViMTgtYmU2Yi00YWMwLWIwODQtMDQ0MzI4OWIzMzc4'})
            patch_url = urlparse(res1.headers['Location']).path
            client.post(
                patch_url + 'merge',
                buffered=True,
                headers={'Authorization': 'Bearer '
                         + 'ZjdjNjQ1ODQtMDc1MC00Y2I2LThjODEtMjkzMmY1ZGFhYmI4'})
            res2 = client.get('/h', headers={'Accept': 'application/ld+json'})
            self.assertEqual(res2.status_code, http.client.SEE_OTHER)
            self.assertEqual(
                urlparse(res2.headers['Location']).path, '/h.jsonld')

            res3 = client.get('/history.jsonld?inline-context')
            self.assertEqual(res3.status_code, http.client.OK)
            self.assertEqual(
                res3.headers['Content-Type'], 'application/ld+json')
            jsonld = res3.get_data(as_text=True)

        g = ConjunctiveGraph()
        g.parse(format='json-ld', data=jsonld)

        # Initial data load
        self.assertIn(  # None means any
            (HOST['h#change-1'], PROV.endedAtTime, None), g)
        self.assertIn(
            (HOST['h#change-1'], PROV.used, HOST['d?version=0']), g)
        self.assertIn(
            (HOST['d?version=0'],
             PROV.specializationOf, HOST['d']), g)
        self.assertIn(
            (HOST['h#change-1'], RDFS.seeAlso, HOST['h#patch-request-1']), g)
        self.assertIn(
            (HOST['h#patch-request-1'], FOAF.page, HOST['patches/1/']), g)
        self.assertIn(
            (HOST['h#change-1'], PROV.used, HOST['h#patch-1']), g)
        self.assertIn(
            (HOST['h#patch-1'],
             FOAF.page, HOST['patches/1/patch.jsonpatch']), g)
        self.assertIn(
            (HOST['h#change-1'],
             PROV.generated, HOST['d?version=1']), g)
        self.assertIn(
            (HOST['d?version=1'],
             PROV.specializationOf, HOST['d']), g)

        # Change from first submitted patch
        self.assertIn(  # None means any
            (HOST['h#change-2'], PROV.startedAtTime, None), g)
        self.assertIn(  # None means any
            (HOST['h#change-2'], PROV.endedAtTime, None), g)
        start = g.value(
            subject=HOST['h#change-2'],
            predicate=PROV.startedAtTime)
        self.assertEqual(start.datatype, XSD.dateTime)
        self.assertRegex(start.value.isoformat(), W3CDTF)
        end = g.value(
            subject=HOST['h#change-2'],
            predicate=PROV.endedAtTime)
        self.assertEqual(end.datatype, XSD.dateTime)
        self.assertRegex(end.value.isoformat(), W3CDTF)
        self.assertIn(
            (HOST['h#change-2'], PROV.wasAssociatedWith,
             URIRef('https://orcid.org/1234-5678-9101-112X')), g)
        self.assertIn(
            (HOST['h#change-2'], PROV.wasAssociatedWith,
             URIRef('https://orcid.org/1211-1098-7654-321X')), g)
        for association in g.subjects(
                predicate=PROV.agent,
                object=URIRef('https://orcid.org/1234-5678-9101-112X')):
            role = g.value(subject=association, predicate=PROV.hadRole)
            self.assertIn(role, (HOST['v#submitted'],
                                 HOST['v#updated']))
        merger = g.value(
            predicate=PROV.agent,
            object=URIRef('https://orcid.org/1211-1098-7654-321X'))
        self.assertIn(
            (HOST['h#change-2'], PROV.qualifiedAssociation, merger), g)
        self.assertIn(
            (merger, PROV.hadRole, HOST['v#merged']), g)
        self.assertIn(
            (HOST['h#change-2'], PROV.used, HOST['d?version=1']), g)
        self.assertIn(
            (HOST['d?version=1'],
             PROV.specializationOf, HOST['d']), g)
        self.assertIn(
            (HOST['h#change-2'], RDFS.seeAlso, HOST['h#patch-request-2']), g)
        self.assertIn(
            (HOST['h#patch-request-2'], FOAF.page, HOST['patches/2/']), g)
        self.assertIn(
            (HOST['h#change-2'], PROV.used, HOST['h#patch-2']), g)
        self.assertIn(
            (HOST['h#patch-2'],
             FOAF.page, HOST['patches/2/patch.jsonpatch']), g)
        self.assertIn(
            (HOST['h#change-2'],
             PROV.generated, HOST['d?version=2']), g)
        self.assertIn(
            (HOST['d?version=2'],
             PROV.specializationOf, HOST['d']), g)
