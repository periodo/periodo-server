import os
import json
import tempfile
import unittest
import http.client
from rdflib import ConjunctiveGraph
from rdflib.namespace import Namespace
from urllib.parse import urlparse
from flask_principal import ActionNeed
from .filepath import filepath
from periodo import app, database, identifier, commands, auth

PERIODO = Namespace('http://n2t.net/ark:/99152/')
PROV = Namespace('http://www.w3.org/ns/prov#')


class TestPatchMethods(unittest.TestCase):

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

    def test_initial_patch(self):
        with self.client as client:
            client.patch(
                '/d/',
                data=self.patch,
                content_type='application/json',
                headers={'Authorization': 'Bearer '
                         + 'NTAwNWViMTgtYmU2Yi00YWMwLWIwODQtMDQ0MzI4OWIzMzc4'})
            created_entities = database.query_db(
                'SELECT created_entities FROM patch_request WHERE id = 1',
                one=True)['created_entities']
            self.assertEqual(
                created_entities,
                '["p0trgkv", "p0trgkv4kxb", "p0trgkvkhrv", "p0trgkvwbjd"]')
            updated_entities = database.query_db(
                'SELECT updated_entities FROM patch_request WHERE id = 1',
                one=True)['updated_entities']
            self.assertEqual(updated_entities, '[]')

    def test_submit_patch(self):
        with self.client as client:
            res = client.patch(
                '/d/',
                data=self.patch,
                content_type='application/json',
                headers={'Authorization': 'Bearer '
                         + 'NTAwNWViMTgtYmU2Yi00YWMwLWIwODQtMDQ0MzI4OWIzMzc4'})
            self.assertEqual(res.status_code, http.client.ACCEPTED)
            patch_id = int(res.headers['Location'].split('/')[-2])
            updated_entities = database.query_db(
                'SELECT updated_entities FROM patch_request WHERE id = ?',
                (patch_id,), one=True)['updated_entities']
            self.assertEqual(updated_entities, '["p0trgkv", "p0trgkvwbjd"]')
            created_entities = database.query_db(
                'SELECT created_entities FROM patch_request WHERE id = ?',
                (patch_id,), one=True)['created_entities']
            self.assertEqual(created_entities, '[]')

    def test_update_patch(self):
        res = self.client.patch(
            '/d/',
            data=self.patch,
            content_type='application/json',
            buffered=True,
            headers={'Authorization': 'Bearer '
                         + 'NTAwNWViMTgtYmU2Yi00YWMwLWIwODQtMDQ0MzI4OWIzMzc4'})
        patch_url = urlparse(res.headers['Location']).path
        jsonpatch_url = patch_url + 'patch.jsonpatch'

        res = self.client.get(jsonpatch_url)
        self.assertEqual(json.loads(self.patch),
                         json.loads(res.get_data(as_text=True)))
        with open(filepath('test-patch-replace-values-2.json')) as f:
            self.patch2 = f.read()
        res = self.client.put(
            jsonpatch_url,
            data=self.patch2,
            content_type='application/json',
            headers={'Authorization': 'Bearer '
                         + 'NTAwNWViMTgtYmU2Yi00YWMwLWIwODQtMDQ0MzI4OWIzMzc4'})
        self.assertEqual(res.status_code, http.client.OK)
        res = self.client.get(jsonpatch_url)
        self.assertEqual(json.loads(self.patch2),
                         json.loads(res.get_data(as_text=True)))

    def test_merge_patch(self):
        with open(filepath('test-patch-adds-items.json')) as f:
            patch = f.read()
        with self.client as client:
            res = client.patch(
                '/d/',
                data=patch,
                content_type='application/json',
                headers={'Authorization': 'Bearer '
                         + 'NTAwNWViMTgtYmU2Yi00YWMwLWIwODQtMDQ0MzI4OWIzMzc4'})
            patch_id = int(res.headers['Location'].split('/')[-2])
            updated_entities = database.query_db(
                'SELECT updated_entities FROM patch_request WHERE id = ?',
                (patch_id,), one=True)['updated_entities']
            self.assertEqual(updated_entities, '["p0trgkv"]')
            created_entities = database.query_db(
                'SELECT created_entities FROM patch_request WHERE id = ?',
                (patch_id,), one=True)['created_entities']
            self.assertEqual(created_entities, '[]')
            patch_url = urlparse(res.headers['Location']).path
            res = client.post(
                patch_url + 'merge',
                buffered=True,
                headers={'Authorization': 'Bearer '
                         + 'ZjdjNjQ1ODQtMDc1MC00Y2I2LThjODEtMjkzMmY1ZGFhYmI4'})
            self.assertEqual(res.status_code, http.client.NO_CONTENT)
            row = database.query_db(
                'SELECT applied_to, resulted_in FROM patch_request WHERE id=?',
                (patch_id,), one=True)
            self.assertEqual(1, row['applied_to'])
            self.assertEqual(2, row['resulted_in'])
            updated_entities = database.query_db(
                'SELECT updated_entities FROM patch_request WHERE id = ?',
                (patch_id,), one=True)['updated_entities']
            self.assertEqual(updated_entities, '["p0trgkv"]')
            created_entities = json.loads(database.query_db(
                'SELECT created_entities FROM patch_request WHERE id = ?',
                (patch_id,), one=True)['created_entities'])
            self.assertEqual(3, len(created_entities))
            for entity_id in created_entities:
                self.assertRegex(entity_id, identifier.IDENTIFIER_RE)

    def test_reject_patch(self):
        with open(filepath('test-patch-adds-items.json')) as f:
            patch = f.read()
        with self.client as client:
            res = client.patch(
                '/d/',
                data=patch,
                content_type='application/json',
                headers={'Authorization': 'Bearer '
                         + 'NTAwNWViMTgtYmU2Yi00YWMwLWIwODQtMDQ0MzI4OWIzMzc4'})
            patch_id = int(res.headers['Location'].split('/')[-2])
            patch_url = urlparse(res.headers['Location']).path
            res = client.post(
                patch_url + 'reject',
                buffered=True,
                headers={'Authorization': 'Bearer '
                         + 'ZjdjNjQ1ODQtMDc1MC00Y2I2LThjODEtMjkzMmY1ZGFhYmI4'})
            self.assertEqual(res.status_code, http.client.NO_CONTENT)
            row = database.query_db(
                'SELECT open, merged FROM patch_request WHERE id=?',
                (patch_id,), one=True)

            self.assertEqual(0, row['open'])
            self.assertEqual(0, row['merged'])

    def test_comment_on_patch(self):
        with open(filepath('test-patch-adds-items.json')) as f:
            patch = f.read()
        with self.client as client:
            res = client.patch(
                '/d/',
                data=patch,
                content_type='application/json',
                headers={'Authorization': 'Bearer '
                         + 'NTAwNWViMTgtYmU2Yi00YWMwLWIwODQtMDQ0MzI4OWIzMzc4'})
            patch_id = int(res.headers['Location'].split('/')[-2])
            patch_url = urlparse(res.headers['Location']).path
            res = client.post(
                patch_url + 'messages',
                data=json.dumps({'message': 'This is a comment'}),
                content_type='application/json',
                headers={'Authorization': 'Bearer ' +
                         'NTAwNWViMTgtYmU2Yi00YWMwLWIwODQtMDQ0MzI4OWIzMzc4'}
            )

            self.assertEqual(res.status_code, http.client.OK)
            self.assertEqual(patch_url, urlparse(res.headers['Location']).path)

            row = database.query_db(
                'SELECT * FROM patch_request_comment WHERE patch_request_id=?',
                (patch_id,), one=True)
            self.assertEqual('http://orcid.org/1234-5678-9101-112X',
                             row['author'])
            self.assertEqual(patch_id, row['patch_request_id'])
            self.assertEqual('This is a comment', row['message'])

            res = client.get(patch_url)
            comments = json.loads(res.get_data(as_text=True)).get('comments')
            self.assertEqual(1, len(comments))

    def test_versioning(self):
        with open(filepath('test-patch-adds-items.json')) as f:
            patch1 = f.read()
        with open(filepath('test-patch-add-definition.json')) as f:
            patch2 = f.read()
        with self.client as client:
            res = client.patch(
                '/d/',
                data=patch1,
                content_type='application/json',
                headers={'Authorization': 'Bearer '
                         + 'NTAwNWViMTgtYmU2Yi00YWMwLWIwODQtMDQ0MzI4OWIzMzc4'})
            patch_url = urlparse(res.headers['Location']).path
            res = client.post(
                patch_url + 'merge',
                buffered=True,
                headers={'Authorization': 'Bearer '
                         + 'ZjdjNjQ1ODQtMDc1MC00Y2I2LThjODEtMjkzMmY1ZGFhYmI4'})
            self.assertEqual(res.status_code, http.client.NO_CONTENT)
            res = client.patch(
                '/d/',
                data=patch2,
                content_type='application/json',
                headers={'Authorization': 'Bearer '
                         + 'NTAwNWViMTgtYmU2Yi00YWMwLWIwODQtMDQ0MzI4OWIzMzc4'})
            patch_url = urlparse(res.headers['Location']).path
            res = client.post(
                patch_url + 'merge',
                buffered=True,
                headers={'Authorization': 'Bearer '
                         + 'ZjdjNjQ1ODQtMDc1MC00Y2I2LThjODEtMjkzMmY1ZGFhYmI4'})
            self.assertEqual(res.status_code, http.client.NO_CONTENT)
            res = client.get('/trgkv?version=0',
                             headers={'Accept': 'application/json'},
                             follow_redirects=True)
            self.assertEqual(res.status_code, http.client.NOT_FOUND)
            for version in range(1, 4):
                res = client.get(
                    '/trgkv?version={}'.format(version),
                    headers={'Accept': 'application/json'})
                self.assertEqual(
                    res.status_code, http.client.SEE_OTHER)
                self.assertEqual(
                    '/' + res.headers['Location'].split('/')[-1],
                    '/trgkv.json?version={}'.format(version))
                res = client.get(
                    '/trgkv.json?version={}'.format(version))
                self.assertEqual(
                    res.status_code, http.client.OK)
                self.assertEqual(
                    res.headers['Content-Type'], 'application/json')
                ctx = json.loads(res.get_data(as_text=True))['@context']
                self.assertEqual(
                    ctx[0],
                    'http://localhost/c?version={}'.format(version)
                )

            res = client.get('/h')

            g = ConjunctiveGraph()
            g.parse(format='json-ld', data=res.get_data(as_text=True))

            for o in g.objects(subject=PERIODO['p0h#change-3'],
                               predicate=PROV.generated):
                path = '/' + urlparse(o).path.split('/')[-1][2:]
                if path == '/trgkv' or path == '/d':
                    continue
                for version in range(0, 3):
                    res = client.get(
                        '{}?version={}'.format(path, version),
                        headers={'Accept': 'application/json'},
                        follow_redirects=True)
                    self.assertEqual(res.status_code, http.client.NOT_FOUND)
                res = client.get('{}?version=3'.format(path),
                                 headers={'Accept': 'application/json'})
                self.assertEqual(res.status_code, http.client.SEE_OTHER)
                self.assertEqual(
                    '/' + res.headers['Location'].split('/')[-1],
                    '{}.json?version=3'.format(path))
                res = client.get(
                    '{}.json?version=3'.format(path))
                self.assertEqual(
                    res.status_code, http.client.OK)
                self.assertEqual(
                    res.headers['Content-Type'], 'application/json')

            for o in g.objects(subject=PERIODO['p0h#change-2'],
                               predicate=PROV.generated):
                path = '/' + urlparse(o).path.split('/')[-1][2:]
                if path == '/trgkv' or path == '/d':
                    continue
                for version in range(0, 2):
                    res = client.get(
                        '{}?version={}'.format(path, version),
                        headers={'Accept': 'application/json'},
                        follow_redirects=True)
                    self.assertEqual(res.status_code, http.client.NOT_FOUND)
                res = client.get('{}?version=3'.format(path),
                                 headers={'Accept': 'application/json'})
                self.assertEqual(res.status_code, http.client.SEE_OTHER)
                self.assertEqual(
                    '/' + res.headers['Location'].split('/')[-1],
                    '{}.json?version=3'.format(path))
                res = client.get('{}.json?version=3'.format(path))
                self.assertEqual(
                    res.status_code, http.client.MOVED_PERMANENTLY)
                self.assertEqual(
                    '/' + res.headers['Location'].split('/')[-1],
                    '{}.json?version=2'.format(path))
                res = client.get(
                    '{}.json?version=2'.format(path))
                self.assertEqual(
                    res.status_code, http.client.OK)
                self.assertEqual(
                    res.headers['Content-Type'], 'application/json')

    def test_context_versioning(self):
        with open(filepath('test-patch-modify-context.json')) as f:
            patch = f.read()
        with self.client as client:
            res = client.patch(
                '/d/',
                data=patch,
                content_type='application/json',
                headers={'Authorization': 'Bearer '
                         + 'NTAwNWViMTgtYmU2Yi00YWMwLWIwODQtMDQ0MzI4OWIzMzc4'})
            patch_url = urlparse(res.headers['Location']).path
            res = client.post(
                patch_url + 'merge',
                buffered=True,
                headers={'Authorization': 'Bearer '
                         + 'ZjdjNjQ1ODQtMDc1MC00Y2I2LThjODEtMjkzMmY1ZGFhYmI4'})
            self.assertEqual(res.status_code, http.client.NO_CONTENT)

            res = client.get('/d.json?version=0',
                             headers={'Accept': 'application/json'},
                             follow_redirects=True)
            self.assertEqual(res.status_code, http.client.OK)
            ctx = json.loads(res.get_data(as_text=True)).get('@context', None)
            self.assertIsNone(ctx)

            res = client.get('/c?version=0',
                             headers={'Accept': 'application/json'},
                             follow_redirects=True)
            self.assertEqual(res.status_code, http.client.NOT_FOUND)

            res = client.get('/d.json?version=1',
                             headers={'Accept': 'application/json'},
                             follow_redirects=True)
            self.assertEqual(res.status_code, http.client.OK)
            ctx = json.loads(res.get_data(as_text=True))['@context']
            self.assertEqual(ctx[0], 'http://localhost/c?version=1')

            res = client.get('/c?version=1',
                             headers={'Accept': 'application/json'},
                             follow_redirects=True)
            self.assertEqual(res.status_code, http.client.OK)
            ctx = json.loads(res.get_data(as_text=True))['@context']
            self.assertNotIn('broader', ctx)

            res = client.get('/d.json?version=2',
                             headers={'Accept': 'application/json'},
                             follow_redirects=True)
            self.assertEqual(res.status_code, http.client.OK)
            ctx = json.loads(res.get_data(as_text=True))['@context']
            self.assertEqual(ctx[0], 'http://localhost/c?version=2')

            res = client.get('/c?version=2',
                             headers={'Accept': 'application/json'},
                             follow_redirects=True)
            self.assertEqual(res.status_code, http.client.OK)
            ctx = json.loads(res.get_data(as_text=True))['@context']
            self.assertIn('broader', ctx)

    def test_remove_definition(self):
        with open(filepath('test-patch-remove-definition.json')) as f:
            patch1 = f.read()
        with self.client as client:
            res = client.patch(
                '/d/',
                data=patch1,
                content_type='application/json',
                headers={'Authorization': 'Bearer '
                         + 'NTAwNWViMTgtYmU2Yi00YWMwLWIwODQtMDQ0MzI4OWIzMzc4'})
            patch_url = urlparse(res.headers['Location']).path
            res = client.post(
                patch_url + 'merge',
                buffered=True,
                headers={'Authorization': 'Bearer '
                         + 'ZjdjNjQ1ODQtMDc1MC00Y2I2LThjODEtMjkzMmY1ZGFhYmI4'})
            self.assertEqual(res.status_code, http.client.NO_CONTENT)
            removed_entities = database.get_removed_entity_keys()
            self.assertEqual(removed_entities, set(['p0trgkvwbjd']))
            res = client.get('/trgkvwbjd',
                             headers={'Accept': 'application/json'},
                             follow_redirects=True)
            self.assertEqual(res.status_code, http.client.GONE)
            res = client.get('/trgkvwbjd.json',
                             headers={'Accept': 'application/json'},
                             follow_redirects=True)
            self.assertEqual(res.status_code, http.client.GONE)
            res = client.get('/trgkvwbjd?version=0',
                             headers={'Accept': 'application/json'},
                             follow_redirects=True)
            self.assertEqual(res.status_code, http.client.NOT_FOUND)
            res = client.get('/trgkvwbjd.json?version=0',
                             headers={'Accept': 'application/json'},
                             follow_redirects=True)
            self.assertEqual(res.status_code, http.client.NOT_FOUND)
            res = client.get('/trgkvwbjd?version=1',
                             headers={'Accept': 'application/json'},
                             follow_redirects=True)
            self.assertEqual(res.status_code, http.client.OK)
            res = client.get('/trgkvwbjd.json?version=1',
                             headers={'Accept': 'application/json'},
                             follow_redirects=True)
            self.assertEqual(res.status_code, http.client.OK)

            res = client.get('/h')

            g = ConjunctiveGraph()
            g.parse(format='json-ld', data=res.get_data(as_text=True))

            invalidated = g.value(subject=PERIODO['p0h#change-2'],
                                  predicate=PROV.invalidated,
                                  any=False)
            self.assertEqual(invalidated, PERIODO['p0trgkvwbjd'])

            generated = list(g.objects(subject=PERIODO['p0h#change-2'],
                                       predicate=PROV.generated))
            self.assertEqual(len(generated), 2)
            self.assertIn(PERIODO['p0d?version=2'], generated)
            self.assertIn(PERIODO['p0trgkv?version=2'], generated)

    def test_remove_collection(self):
        with open(filepath('test-patch-remove-collection.json')) as f:
            patch1 = f.read()
        with self.client as client:
            res = client.patch(
                '/d/',
                data=patch1,
                content_type='application/json',
                headers={'Authorization': 'Bearer '
                         + 'NTAwNWViMTgtYmU2Yi00YWMwLWIwODQtMDQ0MzI4OWIzMzc4'})
            patch_url = urlparse(res.headers['Location']).path
            res = client.post(
                patch_url + 'merge',
                buffered=True,
                headers={'Authorization': 'Bearer '
                         + 'ZjdjNjQ1ODQtMDc1MC00Y2I2LThjODEtMjkzMmY1ZGFhYmI4'})
            self.assertEqual(res.status_code, http.client.NO_CONTENT)
            removed_entities = database.get_removed_entity_keys()
            self.assertEqual(
                removed_entities,
                set(['p0trgkv', 'p0trgkv4kxb', 'p0trgkvkhrv', 'p0trgkvwbjd']))
            res = client.get('/trgkv',
                             headers={'Accept': 'application/json'},
                             follow_redirects=True)
            self.assertEqual(res.status_code, http.client.GONE)
            res = client.get('/trgkv.json',
                             headers={'Accept': 'application/json'},
                             follow_redirects=True)
            self.assertEqual(res.status_code, http.client.GONE)
            res = client.get('/trgkv?version=0',
                             headers={'Accept': 'application/json'},
                             follow_redirects=True)
            self.assertEqual(res.status_code, http.client.NOT_FOUND)
            res = client.get('/trgkv.json?version=0',
                             headers={'Accept': 'application/json'},
                             follow_redirects=True)
            self.assertEqual(res.status_code, http.client.NOT_FOUND)
            res = client.get('/trgkv?version=1',
                             headers={'Accept': 'application/json'},
                             follow_redirects=True)
            self.assertEqual(res.status_code, http.client.OK)
            res = client.get('/trgkv.json?version=1',
                             headers={'Accept': 'application/json'},
                             follow_redirects=True)
            self.assertEqual(res.status_code, http.client.OK)
            res = client.get('/trgkvwbjd',
                             headers={'Accept': 'application/json'},
                             follow_redirects=True)
            self.assertEqual(res.status_code, http.client.GONE)
            res = client.get('/trgkvwbjd.json',
                             headers={'Accept': 'application/json'},
                             follow_redirects=True)
            self.assertEqual(res.status_code, http.client.GONE)
            res = client.get('/trgkvwbjd?version=0',
                             headers={'Accept': 'application/json'},
                             follow_redirects=True)
            self.assertEqual(res.status_code, http.client.NOT_FOUND)
            res = client.get('/trgkvwbjd.json?version=0',
                             headers={'Accept': 'application/json'},
                             follow_redirects=True)
            self.assertEqual(res.status_code, http.client.NOT_FOUND)
            res = client.get('/trgkvwbjd?version=1',
                             headers={'Accept': 'application/json'},
                             follow_redirects=True)
            self.assertEqual(res.status_code, http.client.OK)
            res = client.get('/trgkvwbjd.json?version=1',
                             headers={'Accept': 'application/json'},
                             follow_redirects=True)
            self.assertEqual(res.status_code, http.client.OK)

            res = client.get('/h')

            g = ConjunctiveGraph()
            g.parse(format='json-ld', data=res.get_data(as_text=True))

            invalidated = list(g.objects(subject=PERIODO['p0h#change-2'],
                                         predicate=PROV.invalidated))
            self.assertEqual(len(invalidated), 4)
            self.assertIn(PERIODO['p0trgkv'], invalidated)
            self.assertIn(PERIODO['p0trgkvwbjd'], invalidated)

            generated = g.value(subject=PERIODO['p0h#change-2'],
                                predicate=PROV.generated,
                                any=False)
            self.assertEqual(generated, PERIODO['p0d?version=2'])
