import os
import periodo
import tempfile
import unittest
import http.client
from flask.ext.principal import ActionNeed

class TestAuthentication(unittest.TestCase):

    def setUp(self):
        self.db_fd, periodo.app.config['DATABASE'] = tempfile.mkstemp()
        periodo.app.config['TESTING'] = True
        self.app = periodo.app.test_client()
        periodo.init_db()
        self.identity = periodo.add_user({
            'name': 'Testy Testerson',
            'access_token': '5005eb18-be6b-4ac0-b084-0443289b3378',
            'expires_in': 631138518,
            'orcid': '1234-5678-9101-112X',
        })
        self.expired_identity = periodo.add_user({
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
        res = self.app.patch('/dataset/')
        self.assertEqual(res.status_code, http.client.UNAUTHORIZED)
        self.assertEqual(
            res.headers['WWW-Authenticate'],
            'Bearer realm="PeriodO"')

    def test_unsupported_auth_method(self):
        res = self.app.patch(
            '/dataset/',
            headers={ 'Authorization': 'Basic QWxhZGRpbjpvcGVuIHNlc2FtZQ==' } )
        self.assertEqual(res.status_code, http.client.UNAUTHORIZED)
        self.assertEqual(
            res.headers['WWW-Authenticate'],
            'Bearer realm="PeriodO"')

    def test_malformed_token(self):
        res = self.app.patch(
            '/dataset/',
            headers={ 'Authorization': 'Bearer =!@#$%^&*()_+' } )
        self.assertEqual(res.status_code, http.client.UNAUTHORIZED)
        self.assertEqual(
            res.headers['WWW-Authenticate'],
            'Bearer realm="PeriodO", error="invalid_token", '
            + 'error_description="The access token is malformed", '
            + 'error_uri="http://tools.ietf.org/html/rfc6750#section-6.2.2"')

    def test_token_not_in_database(self):
        res = self.app.patch(
            '/dataset/',
            headers={ 'Authorization': 'Bearer mF_9.B5f-4.1JqM' } )
        self.assertEqual(res.status_code, http.client.UNAUTHORIZED)
        self.assertEqual(
            res.headers['WWW-Authenticate'],
            'Bearer realm="PeriodO", error="invalid_token", '
            + 'error_description="The access token is invalid", '
            + 'error_uri="http://tools.ietf.org/html/rfc6750#section-6.2.2"')

    def test_expired_token(self):
        res = self.app.patch(
            '/dataset/',
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
        self.user_identity = periodo.add_user({
            'name': 'Regular Gal',
            'access_token': '5005eb18-be6b-4ac0-b084-0443289b3378',
            'expires_in': 631138518,
            'orcid': '1234-5678-9101-112X',
        })
        self.admin_identity = periodo.add_user({
            'name': 'Super Admin',
            'access_token': 'f7c64584-0750-4cb6-8c81-2932f5daabb8',
            'expires_in': 3600,
            'orcid': '1211-1098-7654-321X',
        }, (ActionNeed('accept-patch'),))

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

if __name__ == '__main__':
    unittest.main()

