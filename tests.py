import os
import periodo
import tempfile
import unittest
import http.client

class TestAuthentication(unittest.TestCase):

    def setUp(self):
        self.db_fd, periodo.app.config['DATABASE'] = tempfile.mkstemp()
        periodo.app.config['TESTING'] = True
        self.app = periodo.app.test_client()
        periodo.init_db()

    def tearDown(self):
        os.close(self.db_fd)
        os.unlink(periodo.app.config['DATABASE'])

    def test_no_credentials(self):
        res = self.app.patch('/dataset/')
        self.assertEqual(res.status_code, http.client.UNAUTHORIZED)
        self.assertEqual(res.headers['WWW-Authenticate'],
                         'Bearer realm="PeriodO"')

if __name__ == '__main__':
    unittest.main()

