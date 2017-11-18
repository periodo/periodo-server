import os
import tempfile
import unittest
import http.client
from periodo import app, commands, database, auth


class TestAuthentication(unittest.TestCase):

    def setUp(self):
        self.db_fd, app.config['DATABASE'] = tempfile.mkstemp()
        app.config['TESTING'] = True
        self.client = app.test_client()
        commands.init_db()
        with app.app_context():
            self.identity = auth.add_user_or_update_credentials(
                {'name': 'Testy Testerson',
                 'access_token': '5005eb18-be6b-4ac0-b084-0443289b3378',
                 'expires_in': 631138518,
                 'orcid': '1234-5678-9101-112X'})
            self.expired_identity = auth.add_user_or_update_credentials({
                'name': 'Eric Expired',
                'access_token': 'f7c64584-0750-4cb6-8c81-2932f5daabb8',
                'expires_in': -3600,
                'orcid': '1211-1098-7654-321X',
            })
            database.commit()

    def tearDown(self):
        os.close(self.db_fd)
        os.unlink(app.config['DATABASE'])

    def test_add_user(self):
        self.assertEqual(
            self.identity.id, 'http://orcid.org/1234-5678-9101-112X')
        self.assertEqual(
            self.identity.auth_type, 'bearer')
        with app.app_context():
            row = database.query_db(
                'SELECT name, permissions, b64token FROM user WHERE id = ?',
                (self.identity.id,), one=True)
            self.assertEqual(row['name'], 'Testy Testerson')
            self.assertEqual(
                row['permissions'],
                '[["action", "submit-patch"], ["action", "create-bag"]]')
            self.assertEqual(
                row['b64token'],
                b'NTAwNWViMTgtYmU2Yi00YWMwLWIwODQtMDQ0MzI4OWIzMzc4')

    def test_add_expired_user(self):
        self.assertIsNone(self.expired_identity.id)
        self.assertIsNone(self.expired_identity.auth_type)

    def test_no_credentials(self):
        res = self.client.patch('/d/')
        self.assertEqual(res.status_code, http.client.UNAUTHORIZED)
        self.assertEqual(
            res.headers['WWW-Authenticate'],
            'Bearer realm="PeriodO"')

    def test_unsupported_auth_method(self):
        res = self.client.patch(
            '/d/',
            headers={'Authorization': 'Basic QWxhZGRpbjpvcGVuIHNlc2FtZQ=='})
        self.assertEqual(res.status_code, http.client.UNAUTHORIZED)
        self.assertEqual(
            res.headers['WWW-Authenticate'],
            'Bearer realm="PeriodO"')

    def test_malformed_token(self):
        res = self.client.patch(
            '/d/',
            headers={'Authorization': 'Bearer =!@#$%^&*()_+'})
        self.assertEqual(res.status_code, http.client.UNAUTHORIZED)
        self.assertEqual(
            res.headers['WWW-Authenticate'],
            'Bearer realm="PeriodO", error="invalid_token", '
            + 'error_description="The access token is malformed", '
            + 'error_uri="http://tools.ietf.org/html/rfc6750#section-6.2.2"')

    def test_token_not_in_database(self):
        res = self.client.patch(
            '/d/',
            headers={'Authorization': 'Bearer mF_9.B5f-4.1JqM'})
        self.assertEqual(res.status_code, http.client.UNAUTHORIZED)
        self.assertEqual(
            res.headers['WWW-Authenticate'],
            'Bearer realm="PeriodO", error="invalid_token", '
            + 'error_description="The access token is invalid", '
            + 'error_uri="http://tools.ietf.org/html/rfc6750#section-6.2.2"')

    def test_expired_token(self):
        res = self.client.patch(
            '/d/',
            headers={'Authorization': 'Bearer '
                     + 'ZjdjNjQ1ODQtMDc1MC00Y2I2LThjODEtMjkzMmY1ZGFhYmI4'})
        self.assertEqual(res.status_code, http.client.UNAUTHORIZED)
        self.assertEqual(
            res.headers['WWW-Authenticate'],
            'Bearer realm="PeriodO", error="invalid_token", '
            + 'error_description="The access token expired", '
            + 'error_uri="http://tools.ietf.org/html/rfc6750#section-6.2.2"')
