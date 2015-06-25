import os
import json
import periodo
import identifier
import tempfile
import unittest
import http.client
from urllib.parse import urlparse
from flask.ext.principal import ActionNeed
from .filepath import filepath


class TestPatchMethods(unittest.TestCase):

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
        with open(filepath('test-patch-replace-values-1.json')) as f:
            self.patch = f.read()

    def tearDown(self):
        os.close(self.db_fd)
        os.unlink(periodo.app.config['DATABASE'])

    def test_initial_patch(self):
        with self.app as client:
            client.patch(
                '/d/',
                data=self.patch,
                content_type='application/json',
                headers={'Authorization': 'Bearer '
                         + 'NTAwNWViMTgtYmU2Yi00YWMwLWIwODQtMDQ0MzI4OWIzMzc4'})
            affected_entities = periodo.query_db(
                'SELECT affected_entities FROM patch_request WHERE id = 1',
                one=True)['affected_entities']
            self.assertEqual(affected_entities, '["p0trgkv", "p0trgkvwbjd"]')

    def test_submit_patch(self):
        with self.app as client:
            res = client.patch(
                '/d/',
                data=self.patch,
                content_type='application/json',
                headers={'Authorization': 'Bearer '
                         + 'NTAwNWViMTgtYmU2Yi00YWMwLWIwODQtMDQ0MzI4OWIzMzc4'})
            self.assertEqual(res.status_code, http.client.ACCEPTED)
            patch_id = int(res.headers['Location'].split('/')[-2])
            affected_entities = periodo.query_db(
                'SELECT affected_entities FROM patch_request WHERE id = ?',
                (patch_id,), one=True)['affected_entities']
            self.assertEqual(affected_entities, '["p0trgkv", "p0trgkvwbjd"]')

    def test_update_patch(self):
        res = self.app.patch(
            '/d/',
            data=self.patch,
            content_type='application/json',
            headers={'Authorization': 'Bearer '
                         + 'NTAwNWViMTgtYmU2Yi00YWMwLWIwODQtMDQ0MzI4OWIzMzc4'})
        patch_url = urlparse(res.headers['Location']).path
        jsonpatch_url = patch_url + 'patch.jsonpatch'

        res = self.app.get(jsonpatch_url)
        self.assertEqual(json.loads(self.patch),
                         json.loads(res.get_data(as_text=True)))
        with open(filepath('test-patch-replace-values-2.json')) as f:
            self.patch2 = f.read()
        res = self.app.put(
            jsonpatch_url,
            data=self.patch2,
            content_type='application/json',
            headers={'Authorization': 'Bearer '
                         + 'NTAwNWViMTgtYmU2Yi00YWMwLWIwODQtMDQ0MzI4OWIzMzc4'})
        self.assertEqual(res.status_code, http.client.OK)
        res = self.app.get(jsonpatch_url)
        self.assertEqual(json.loads(self.patch2),
                         json.loads(res.get_data(as_text=True)))

    def test_merge_patch(self):
        with open(filepath('test-patch-adds-items.json')) as f:
            patch = f.read()
        with self.app as client:
            res = client.patch(
                '/d/',
                data=patch,
                content_type='application/json',
                headers={'Authorization': 'Bearer '
                         + 'NTAwNWViMTgtYmU2Yi00YWMwLWIwODQtMDQ0MzI4OWIzMzc4'})
            patch_id = int(res.headers['Location'].split('/')[-2])
            affected_entities = periodo.query_db(
                'SELECT affected_entities FROM patch_request WHERE id = ?',
                (patch_id,), one=True)['affected_entities']
            self.assertEqual(affected_entities, '["p0trgkv"]')
            patch_url = urlparse(res.headers['Location']).path
            res = client.post(
                patch_url + 'merge',
                headers={'Authorization': 'Bearer '
                         + 'ZjdjNjQ1ODQtMDc1MC00Y2I2LThjODEtMjkzMmY1ZGFhYmI4'})
            self.assertEqual(res.status_code, http.client.NO_CONTENT)
            row = periodo.query_db(
                'SELECT applied_to, resulted_in FROM patch_request WHERE id=?',
                (patch_id,), one=True)
            self.assertEqual(1, row['applied_to'])
            self.assertEqual(2, row['resulted_in'])
            affected_entities = json.loads(periodo.query_db(
                'SELECT affected_entities FROM patch_request WHERE id = ?',
                (patch_id,), one=True)['affected_entities'])
            self.assertEqual(4, len(affected_entities))
            for entity_id in affected_entities:
                self.assertRegex(entity_id, identifier.IDENTIFIER_RE)
