import os
import periodo
import tempfile
import unittest
import http.client
from urllib.parse import urlparse
from flask.ext.principal import ActionNeed


def setUpModule():
    os.chdir('test')


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
            headers={'Authorization': 'Bearer '
                     + 'ZjdlMDBjMDItNmY5Ny00NjM2LTg0OTktMDM3NDQ2ZDk1NDQ2'})
        self.assertEqual(res.status_code, http.client.FORBIDDEN)
        self.assertEqual(
            res.headers['WWW-Authenticate'],
            'Bearer realm="PeriodO", error="insufficient_scope", '
            + 'error_description='
            + '"The access token does not provide sufficient privileges", '
            + 'error_uri="http://tools.ietf.org/html/rfc6750#section-6.2.3"')

    def test_authorized_user(self):
        with self.app as client:
            res = client.patch(
                '/d/',
                data=self.patch,
                content_type='application/json',
                headers={'Authorization': 'Bearer '
                         + 'NTAwNWViMTgtYmU2Yi00YWMwLWIwODQtMDQ0MzI4OWIzMzc4'})
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
            headers={'Authorization': 'Bearer '
                     + 'NTAwNWViMTgtYmU2Yi00YWMwLWIwODQtMDQ0MzI4OWIzMzc4'})

        # Test that there's NO link header
        patch_url = urlparse(res.headers['Location']).path
        res = self.app.get(patch_url, headers={
            'Authorization': 'Bearer '
            + 'NTAwNWViMTgtYmU2Yi00YWMwLWIwODQtMDQ0MzI4OWIzMzc4'})
        self.assertEqual(res.headers.get('Link'), None)

        res = self.app.post(
            patch_url + 'merge',
            headers={'Authorization': 'Bearer '
                     + 'NTAwNWViMTgtYmU2Yi00YWMwLWIwODQtMDQ0MzI4OWIzMzc4'})
        self.assertEqual(res.status_code, http.client.FORBIDDEN)
        self.assertEqual(
            res.headers['WWW-Authenticate'],
            'Bearer realm="PeriodO", error="insufficient_scope", '
            + 'error_description='
            + '"The access token does not provide sufficient privileges", '
            + 'error_uri="http://tools.ietf.org/html/rfc6750#section-6.2.3"')

    def test_admin_merge(self):
        with self.app as client:
            res = client.patch(
                '/d/',
                data=self.patch,
                content_type='application/json',
                headers={'Authorization': 'Bearer '
                         + 'NTAwNWViMTgtYmU2Yi00YWMwLWIwODQtMDQ0MzI4OWIzMzc4'})
            patch_id = int(res.headers['Location'].split('/')[-2])

            # Test that there's a link header
            patch_url = urlparse(res.headers['Location']).path
            res = self.app.get(patch_url, headers={
                'Authorization': 'Bearer '
                + 'ZjdjNjQ1ODQtMDc1MC00Y2I2LThjODEtMjkzMmY1ZGFhYmI4'})
            self.assertEqual(res.headers.get('Link'),
                             '<{}>;rel="merge"'.format(patch_url + 'merge'))

            res = client.post(
                patch_url + 'merge',
                headers={'Authorization': 'Bearer '
                         + 'ZjdjNjQ1ODQtMDc1MC00Y2I2LThjODEtMjkzMmY1ZGFhYmI4'})
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
            headers={'Authorization': 'Bearer '
                         + 'NTAwNWViMTgtYmU2Yi00YWMwLWIwODQtMDQ0MzI4OWIzMzc4'})
        res = self.app.put(
            urlparse(res.headers['Location']).path + 'patch.jsonpatch',
            data=self.patch,
            content_type='application/json',
            headers={'Authorization': 'Bearer '
                     + 'ZjdjNjQ1ODQtMDc1MC00Y2I2LThjODEtMjkzMmY1ZGFhYmI4'})
        self.assertEqual(res.status_code, http.client.FORBIDDEN)
        self.assertEqual(
            res.headers['WWW-Authenticate'],
            'Bearer realm="PeriodO", error="insufficient_scope", '
            + 'error_description='
            + '"The access token does not provide sufficient privileges", '
            + 'error_uri="http://tools.ietf.org/html/rfc6750#section-6.2.3"')

    def test_creator_patch_update(self):
        with self.app as client:
            res = client.patch(
                '/d/',
                data=self.patch,
                content_type='application/json',
                headers={'Authorization': 'Bearer '
                         + 'NTAwNWViMTgtYmU2Yi00YWMwLWIwODQtMDQ0MzI4OWIzMzc4'})
            res = client.put(
                urlparse(res.headers['Location']).path + 'patch.jsonpatch',
                data=self.patch,
                content_type='application/json',
                headers={'Authorization': 'Bearer '
                         + 'NTAwNWViMTgtYmU2Yi00YWMwLWIwODQtMDQ0MzI4OWIzMzc4'})
            self.assertEqual(res.status_code, http.client.OK)

    def test_update_merged_patch(self):
        with self.app as client:
            res = client.patch(
                '/d/',
                data=self.patch,
                content_type='application/json',
                headers={'Authorization': 'Bearer '
                         + 'NTAwNWViMTgtYmU2Yi00YWMwLWIwODQtMDQ0MzI4OWIzMzc4'})
            patch_path = urlparse(res.headers['Location']).path
            res = client.post(
                patch_path + 'merge',
                headers={'Authorization': 'Bearer '
                         + 'ZjdjNjQ1ODQtMDc1MC00Y2I2LThjODEtMjkzMmY1ZGFhYmI4'})
            res = client.put(
                patch_path + 'patch.jsonpatch',
                data=self.patch,
                content_type='application/json',
                headers={'Authorization': 'Bearer '
                         + 'NTAwNWViMTgtYmU2Yi00YWMwLWIwODQtMDQ0MzI4OWIzMzc4'})
        self.assertEqual(res.status_code, http.client.FORBIDDEN)
        self.assertEqual(
            res.headers['WWW-Authenticate'],
            'Bearer realm="PeriodO", error="insufficient_scope", '
            + 'error_description='
            + '"The access token does not provide sufficient privileges", '
            + 'error_uri="http://tools.ietf.org/html/rfc6750#section-6.2.3"')