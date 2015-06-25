import os
import periodo
import tempfile
import unittest
import http.client
from rdflib import ConjunctiveGraph, URIRef
from rdflib.namespace import Namespace
from urllib.parse import urlparse
from flask.ext.principal import ActionNeed
from .filepath import filepath

VOID = Namespace('http://rdfs.org/ns/void#')
SKOS = Namespace('http://www.w3.org/2004/02/skos/core#')
PERIODO = Namespace('http://n2t.net/ark:/99152/')
FOAF = Namespace('http://xmlns.com/foaf/0.1/')
PROV = Namespace('http://www.w3.org/ns/prov#')


class TestProvenance(unittest.TestCase):

    def setUp(self):
        self.db_fd, periodo.app.config['DATABASE'] = tempfile.mkstemp()
        periodo.app.config['TESTING'] = True
        self.app = periodo.app.test_client()
        periodo.init_db()
        periodo.load_data(filepath('test-data.json'))
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

    def tearDown(self):
        os.close(self.db_fd)
        os.unlink(periodo.app.config['DATABASE'])

    def test_get_history(self):
        with open(filepath('test-patch-adds-items.json')) as f:
            patch = f.read()

        with self.app as client:
            res1 = client.patch(
                '/d/',
                data=patch,
                content_type='application/json',
                headers={'Authorization': 'Bearer '
                         + 'NTAwNWViMTgtYmU2Yi00YWMwLWIwODQtMDQ0MzI4OWIzMzc4'})
            patch_url = urlparse(res1.headers['Location']).path
            client.post(
                patch_url + 'merge',
                headers={'Authorization': 'Bearer '
                         + 'ZjdjNjQ1ODQtMDc1MC00Y2I2LThjODEtMjkzMmY1ZGFhYmI4'})
            res2 = client.get('/h')
            self.assertEqual(res2.status_code, http.client.OK)
            self.assertEqual(
                res2.headers['Content-Type'], 'application/ld+json')
            jsonld = res2.get_data(as_text=True)
            #print(jsonld)

        g = ConjunctiveGraph()
        g.parse(format='json-ld', data=jsonld)
        #print(g.serialize(format='turtle').decode('utf-8'))

        # Initial data load
        self.assertIn(  # None means any
            (PERIODO['p0h#change-1'], PROV.endedAtTime, None), g)
        self.assertIn(
            (PERIODO['p0h#change-1'], PROV.used, PERIODO['p0d?version=0']), g)
        self.assertIn(
            (PERIODO['p0d?version=0'],
             PROV.specializationOf, PERIODO['p0d']), g)
        self.assertIn(
            (PERIODO['p0h#change-1'], PROV.used, PERIODO['p0h#patch-1']), g)
        self.assertIn(
            (PERIODO['p0h#patch-1'],
             FOAF.page, PERIODO['p0patches/1/patch.jsonpatch']), g)
        self.assertIn(
            (PERIODO['p0h#change-1'],
             PROV.generated, PERIODO['p0d?version=1']), g)
        self.assertIn(
            (PERIODO['p0d?version=1'],
             PROV.specializationOf, PERIODO['p0d']), g)
        self.assertIn(
            (PERIODO['p0h#change-1'],
             PROV.generated, PERIODO['p0trgkv?version=1']), g)
        self.assertIn(
            (PERIODO['p0trgkv?version=1'],
             PROV.specializationOf, PERIODO['p0trgkv']), g)
        self.assertIn(
            (PERIODO['p0h#change-1'],
             PROV.generated, PERIODO['p0trgkvwbjd?version=1']), g)
        self.assertIn(
            (PERIODO['p0trgkvwbjd?version=1'],
             PROV.specializationOf, PERIODO['p0trgkvwbjd']), g)

        # Change from first submitted patch
        self.assertIn(  # None means any
            (PERIODO['p0h#change-2'], PROV.startedAtTime, None), g)
        self.assertIn(  # None means any
            (PERIODO['p0h#change-2'], PROV.endedAtTime, None), g)
        self.assertIn(
            (PERIODO['p0h#change-2'], PROV.wasAssociatedWith,
             URIRef('http://orcid.org/1234-5678-9101-112X')), g)
        self.assertIn(
            (PERIODO['p0h#change-2'], PROV.wasAssociatedWith,
             URIRef('http://orcid.org/1211-1098-7654-321X')), g)
        for association in g.subjects(
                predicate=PROV.agent,
                object=URIRef('http://orcid.org/1234-5678-9101-112X')):
            role = g.value(subject=association, predicate=PROV.hadRole)
            self.assertIn(role, (PERIODO['p0v#submitted'],
                                 PERIODO['p0v#updated']))
        merger = g.value(
            predicate=PROV.agent,
            object=URIRef('http://orcid.org/1211-1098-7654-321X'))
        self.assertIn(
            (PERIODO['p0h#change-2'], PROV.qualifiedAssociation, merger), g)
        self.assertIn(
            (merger, PROV.hadRole, PERIODO['p0v#merged']), g)
        self.assertIn(
            (PERIODO['p0h#change-2'], PROV.used, PERIODO['p0d?version=1']), g)
        self.assertIn(
            (PERIODO['p0d?version=1'],
             PROV.specializationOf, PERIODO['p0d']), g)
        self.assertIn(
            (PERIODO['p0h#change-2'], PROV.used, PERIODO['p0h#patch-2']), g)
        self.assertIn(
            (PERIODO['p0h#patch-2'],
             FOAF.page, PERIODO['p0patches/2/patch.jsonpatch']), g)
        self.assertIn(
            (PERIODO['p0h#change-2'],
             PROV.generated, PERIODO['p0d?version=2']), g)
        self.assertIn(
            (PERIODO['p0d?version=2'],
             PROV.specializationOf, PERIODO['p0d']), g)
        self.assertIn(
            (PERIODO['p0h#change-2'],
             PROV.generated, PERIODO['p0trgkv?version=2']), g)
        self.assertIn(
            (PERIODO['p0trgkv?version=2'],
             PROV.specializationOf, PERIODO['p0trgkv']), g)
        self.assertIn(
            (PERIODO['p0trgkv?version=2'],
             PROV.wasRevisionOf, PERIODO['p0trgkv?version=1']), g)

        entities = 0
        for _, _, version in g.triples(
                (PERIODO['p0h#change-2'], PROV.generated, None)):
            entity = g.value(subject=version, predicate=PROV.specializationOf)
            self.assertEqual(str(entity) + '?version=2', str(version))
            entities += 1
        self.assertEqual(entities, 5)
