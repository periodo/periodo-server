import os
import json
import tempfile
import unittest
import http.client
from rdflib.namespace import Namespace
from urllib.parse import urlparse
from flask_principal import ActionNeed
from .filepath import filepath
from periodo import app, database, commands, auth
from uuid import UUID

PERIODO = Namespace('http://n2t.net/ark:/99152/')
PROV = Namespace('http://www.w3.org/ns/prov#')


class TestBags(unittest.TestCase):

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
            }, (ActionNeed('create-bag'),))
            database.commit()

    def tearDown(self):
        os.close(self.db_fd)
        os.unlink(app.config['DATABASE'])

    def test_create_bag(self):
        with open(filepath('test-bag.json')) as f:
            bag_json = f.read()
        with open(filepath('test-bag.jsonld')) as f:
            bag_jsonld = f.read()
        with self.client as client:
            id = UUID('6f2c64e2-c65f-4e2d-b028-f89dfb71ce69')
            res = client.put(
                '/bags/%s' % id,
                data=bag_json,
                content_type='application/json',
                headers={'Authorization': 'Bearer '
                         + 'NTAwNWViMTgtYmU2Yi00YWMwLWIwODQtMDQ0MzI4OWIzMzc4'})
            self.assertEqual(res.status_code, http.client.CREATED)
            bag_url = urlparse(res.headers['Location'])
            self.assertEqual('/bags/%s' % id, bag_url.path)
            self.assertEqual('version=0', bag_url.query)
            res = client.get(res.headers['Location'])
            self.assertTrue('Last-Modified' in res.headers)
            self.assertEqual(
                res.headers['Etag'],
                'W/"bag-6f2c64e2-c65f-4e2d-b028-f89dfb71ce69-version-0"')
            self.maxDiff = None
            self.assertEqual(
                json.loads(bag_jsonld),
                json.loads(res.get_data(as_text=True)))

    def test_if_none_match(self):
        with open(filepath('test-bag.json')) as f:
            bag_json = f.read()
        with self.client as client:
            id = UUID('6f2c64e2-c65f-4e2d-b028-f89dfb71ce69')
            res = client.put(
                '/bags/%s' % id,
                data=bag_json,
                content_type='application/json',
                headers={'Authorization': 'Bearer '
                         + 'NTAwNWViMTgtYmU2Yi00YWMwLWIwODQtMDQ0MzI4OWIzMzc4'})
            self.assertEqual(res.status_code, http.client.CREATED)
            res = client.get(
                res.headers['Location'],
                buffered=True,
                headers={
                    'If-None-Match':
                    'W/"bag-6f2c64e2-c65f-4e2d-b028-f89dfb71ce69-version-0"'})
            self.assertEqual(res.status_code, http.client.NOT_MODIFIED)

    def test_create_bag_requires_auth(self):
        with open(filepath('test-bag.json')) as f:
            bag_json = f.read()
        with self.client as client:
            id = UUID('6f2c64e2-c65f-4e2d-b028-f89dfb71ce69')
            res = client.put(
                '/bags/%s' % id,
                data=bag_json,
                content_type='application/json')
            self.assertEqual(res.status_code, http.client.UNAUTHORIZED)

    def test_create_bag_requires_title(self):
        with open(filepath('test-bag.json')) as f:
            bag_json = json.loads(f.read())
            del bag_json['title']
        with self.client as client:
            id = UUID('6f2c64e2-c65f-4e2d-b028-f89dfb71ce69')
            res = client.put(
                '/bags/%s' % id,
                data=json.dumps(bag_json),
                content_type='application/json',
                headers={'Authorization': 'Bearer '
                         + 'NTAwNWViMTgtYmU2Yi00YWMwLWIwODQtMDQ0MzI4OWIzMzc4'})
            self.assertEqual(res.status_code, http.client.BAD_REQUEST)
            self.assertEqual(
                json.loads(res.get_data(as_text=True))['message'],
                'A bag must have a title')

    def test_create_bag_requires_items_array(self):
        with open(filepath('test-bag.json')) as f:
            bag_json = json.loads(f.read())
            del bag_json['items']
        with self.client as client:
            id = UUID('6f2c64e2-c65f-4e2d-b028-f89dfb71ce69')
            res = client.put(
                '/bags/%s' % id,
                data=json.dumps(bag_json),
                content_type='application/json',
                headers={'Authorization': 'Bearer '
                         + 'NTAwNWViMTgtYmU2Yi00YWMwLWIwODQtMDQ0MzI4OWIzMzc4'})
            self.assertEqual(res.status_code, http.client.BAD_REQUEST)
            self.assertEqual(
                json.loads(res.get_data(as_text=True))['message'],
                'A bag must have at least two items')

    def test_create_bag_requires_minimum_of_two_items(self):
        with open(filepath('test-bag.json')) as f:
            bag_json = json.loads(f.read())
            bag_json['items'].pop()
        with self.client as client:
            id = UUID('6f2c64e2-c65f-4e2d-b028-f89dfb71ce69')
            res = client.put(
                '/bags/%s' % id,
                data=json.dumps(bag_json),
                content_type='application/json',
                headers={'Authorization': 'Bearer '
                         + 'NTAwNWViMTgtYmU2Yi00YWMwLWIwODQtMDQ0MzI4OWIzMzc4'})
            self.assertEqual(res.status_code, http.client.BAD_REQUEST)
            self.assertEqual(
                json.loads(res.get_data(as_text=True))['message'],
                'A bag must have at least two items')

    def test_create_bag_requires_items_be_periodo_ids(self):
        with open(filepath('test-bag.json')) as f:
            bag_json = json.loads(f.read())
            bag_json['items'].append('foobar')
        with self.client as client:
            id = UUID('6f2c64e2-c65f-4e2d-b028-f89dfb71ce69')
            res = client.put(
                '/bags/%s' % id,
                data=json.dumps(bag_json),
                content_type='application/json',
                headers={'Authorization': 'Bearer '
                         + 'NTAwNWViMTgtYmU2Yi00YWMwLWIwODQtMDQ0MzI4OWIzMzc4'})
            self.assertEqual(res.status_code, http.client.BAD_REQUEST)
            self.assertEqual(
                json.loads(res.get_data(as_text=True))['message'],
                'No resource with key: foobar')

    def test_update_bag(self):
        with open(filepath('test-bag.json')) as f:
            bag_json = f.read()
        with open(filepath('test-bag.jsonld')) as f:
            bag_jsonld = f.read()
        with open(filepath('test-bag-updated.json')) as f:
            updated_bag_json = f.read()
        with open(filepath('test-bag-updated.jsonld')) as f:
            updated_bag_jsonld = f.read()
        with self.client as client:
            id = UUID('6f2c64e2-c65f-4e2d-b028-f89dfb71ce69')
            res = client.put(
                '/bags/%s' % id,
                data=bag_json,
                content_type='application/json',
                headers={'Authorization': 'Bearer '
                         + 'NTAwNWViMTgtYmU2Yi00YWMwLWIwODQtMDQ0MzI4OWIzMzc4'})
            self.assertEqual(res.status_code, http.client.CREATED)
            bag_url_v0 = urlparse(res.headers['Location'])
            self.assertEqual('/bags/%s' % id, bag_url_v0.path)
            self.assertEqual('version=0', bag_url_v0.query)

            res = client.put(
                '/bags/%s' % id,
                data=updated_bag_json,
                content_type='application/json',
                headers={'Authorization': 'Bearer '
                         + 'NTAwNWViMTgtYmU2Yi00YWMwLWIwODQtMDQ0MzI4OWIzMzc4'})
            self.assertEqual(res.status_code, http.client.CREATED)
            bag_url_v1 = urlparse(res.headers['Location'])
            self.assertEqual('/bags/%s' % id, bag_url_v1.path)
            self.assertEqual('version=1', bag_url_v1.query)

            res = client.get('/bags/%s' % id)
            self.maxDiff = None
            self.assertEqual(
                json.loads(updated_bag_jsonld),
                json.loads(res.get_data(as_text=True)))

            res = client.get('/bags/%s?version=0' % id)
            self.maxDiff = None
            self.assertEqual(
                json.loads(bag_jsonld),
                json.loads(res.get_data(as_text=True)))

            res = client.get('/bags/%s?version=1' % id)
            self.maxDiff = None
            self.assertEqual(
                json.loads(updated_bag_jsonld),
                json.loads(res.get_data(as_text=True)))

    def test_update_bag_using_jsonld(self):
        with open(filepath('test-bag.json')) as f:
            bag_json = f.read()
        with open(filepath('test-bag.jsonld')) as f:
            bag_jsonld = f.read()
        with open(filepath('test-bag-updated.jsonld')) as f:
            updated_bag_jsonld = f.read()
        with self.client as client:
            id = UUID('6f2c64e2-c65f-4e2d-b028-f89dfb71ce69')
            res = client.put(
                '/bags/%s' % id,
                data=bag_json,
                content_type='application/json',
                headers={'Authorization': 'Bearer '
                         + 'NTAwNWViMTgtYmU2Yi00YWMwLWIwODQtMDQ0MzI4OWIzMzc4'})
            self.assertEqual(res.status_code, http.client.CREATED)
            bag_url_v0 = urlparse(res.headers['Location'])
            self.assertEqual('/bags/%s' % id, bag_url_v0.path)
            self.assertEqual('version=0', bag_url_v0.query)

            res = client.put(
                '/bags/%s' % id,
                data=updated_bag_jsonld,
                content_type='application/json',
                headers={'Authorization': 'Bearer '
                         + 'NTAwNWViMTgtYmU2Yi00YWMwLWIwODQtMDQ0MzI4OWIzMzc4'})
            self.assertEqual(res.status_code, http.client.CREATED)
            bag_url_v1 = urlparse(res.headers['Location'])
            self.assertEqual('/bags/%s' % id, bag_url_v1.path)
            self.assertEqual('version=1', bag_url_v1.query)

            res = client.get('/bags/%s' % id)
            self.maxDiff = None
            self.assertEqual(
                json.loads(updated_bag_jsonld),
                json.loads(res.get_data(as_text=True)))

            res = client.get('/bags/%s?version=0' % id)
            self.maxDiff = None
            self.assertEqual(
                json.loads(bag_jsonld),
                json.loads(res.get_data(as_text=True)))

            res = client.get('/bags/%s?version=1' % id)
            self.maxDiff = None
            self.assertEqual(
                json.loads(updated_bag_jsonld),
                json.loads(res.get_data(as_text=True)))

    def test_update_bag_must_be_owner(self):
        with open(filepath('test-bag.json')) as f:
            bag_json = f.read()
        with open(filepath('test-bag-updated.json')) as f:
            updated_bag_json = f.read()
        with self.client as client:
            id = UUID('6f2c64e2-c65f-4e2d-b028-f89dfb71ce69')
            res = client.put(
                '/bags/%s' % id,
                data=bag_json,
                content_type='application/json',
                headers={'Authorization': 'Bearer '
                         + 'ZjdjNjQ1ODQtMDc1MC00Y2I2LThjODEtMjkzMmY1ZGFhYmI4'})
            self.assertEqual(res.status_code, http.client.CREATED)
            bag_url_v0 = urlparse(res.headers['Location'])
            self.assertEqual('/bags/%s' % id, bag_url_v0.path)
            self.assertEqual('version=0', bag_url_v0.query)

            res = client.put(
                '/bags/%s' % id,
                data=updated_bag_json,
                content_type='application/json',
                headers={'Authorization': 'Bearer '
                         + 'NTAwNWViMTgtYmU2Yi00YWMwLWIwODQtMDQ0MzI4OWIzMzc4'})
            self.assertEqual(res.status_code, http.client.FORBIDDEN)
