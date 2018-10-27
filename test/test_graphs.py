import os
import json
import tempfile
import unittest
import http.client
from urllib.parse import urlparse
from flask_principal import ActionNeed
from .filepath import filepath
from periodo import app, database, commands, auth


class TestGraphs(unittest.TestCase):

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
            }, (ActionNeed('create-graph'),))
            database.commit()

    def tearDown(self):
        os.close(self.db_fd)
        os.unlink(app.config['DATABASE'])

    def test_put_graph(self):
        with open(filepath('test-graph.json')) as f:
            graph_json = f.read()
        with self.client as client:
            id = 'places/us-states'
            res = client.put(
                '/graphs/%s' % id,
                data=graph_json,
                content_type='application/json',
                headers={'Authorization': 'Bearer '
                         + 'ZjdjNjQ1ODQtMDc1MC00Y2I2LThjODEtMjkzMmY1ZGFhYmI4'})
            self.assertEqual(res.status_code, http.client.CREATED)
            graph_url = urlparse(res.headers['Location'])
            self.assertEqual('/graphs/%s' % id, graph_url.path)
            self.assertEqual('version=0', graph_url.query)
            res = client.get(res.headers['Location'])
            self.assertTrue('Last-Modified' in res.headers)
            self.assertEqual(
                res.headers['Etag'],
                'W/"graph-places/us-states-version-0"')
            res = client.get('/graphs/')
            self.assertEqual(res.status_code, http.client.OK)
            data = json.loads(res.get_data(as_text=True))
            self.assertEqual(
                {'http://localhost.localdomain:5000/d/',
                 'http://localhost.localdomain:5000/graphs/%s' % id},
                set(data['graphs'].keys()))

    def test_if_none_match(self):
        with open(filepath('test-graph.json')) as f:
            graph_json = f.read()
        with self.client as client:
            id = 'places/us-states'
            res = client.put(
                '/graphs/%s' % id,
                data=graph_json,
                content_type='application/json',
                headers={'Authorization': 'Bearer '
                         + 'ZjdjNjQ1ODQtMDc1MC00Y2I2LThjODEtMjkzMmY1ZGFhYmI4'})
            self.assertEqual(res.status_code, http.client.CREATED)
            res = client.get(
                res.headers['Location'],
                buffered=True,
                headers={
                    'If-None-Match':
                    'W/"graph-places/us-states-version-0"'})
            self.assertEqual(res.status_code, http.client.NOT_MODIFIED)

    def test_put_graph_requires_permission(self):
        with open(filepath('test-graph.json')) as f:
            graph_json = f.read()
        with self.client as client:
            id = 'places/us-states'
            res = client.put(
                '/graphs/%s' % id,
                data=graph_json,
                content_type='application/json',
                headers={'Authorization': 'Bearer '
                         + 'NTAwNWViMTgtYmU2Yi00YWMwLWIwODQtMDQ0MzI4OWIzMzc4'})
            self.assertEqual(res.status_code, http.client.FORBIDDEN)

    def test_delete_graph_requires_auth(self):
        with open(filepath('test-graph.json')) as f:
            graph_json = f.read()
        with self.client as client:
            id = 'places/us-states'
            res = client.put(
                '/graphs/%s' % id,
                data=graph_json,
                content_type='application/json',
                headers={'Authorization': 'Bearer '
                         + 'ZjdjNjQ1ODQtMDc1MC00Y2I2LThjODEtMjkzMmY1ZGFhYmI4'})
            self.assertEqual(res.status_code, http.client.CREATED)
            res = client.delete('/graphs/%s' % id)
            self.assertEqual(res.status_code, http.client.UNAUTHORIZED)

    def test_update_graph(self):
        with open(filepath('test-graph.json')) as f:
            graph_json = f.read()
        with open(filepath('test-graph-updated.json')) as f:
            updated_graph_json = f.read()
        with self.client as client:
            id = 'places/us-states'
            res = client.put(
                '/graphs/%s' % id,
                data=graph_json,
                content_type='application/json',
                headers={'Authorization': 'Bearer '
                         + 'ZjdjNjQ1ODQtMDc1MC00Y2I2LThjODEtMjkzMmY1ZGFhYmI4'})
            self.assertEqual(res.status_code, http.client.CREATED)
            graph_url_v0 = urlparse(res.headers['Location'])
            self.assertEqual('/graphs/%s' % id, graph_url_v0.path)
            self.assertEqual('version=0', graph_url_v0.query)

            res = client.put(
                '/graphs/%s' % id,
                data=updated_graph_json,
                content_type='application/json',
                headers={'Authorization': 'Bearer '
                         + 'ZjdjNjQ1ODQtMDc1MC00Y2I2LThjODEtMjkzMmY1ZGFhYmI4'})
            self.assertEqual(res.status_code, http.client.CREATED)
            graph_url_v1 = urlparse(res.headers['Location'])
            self.assertEqual('/graphs/%s' % id, graph_url_v1.path)
            self.assertEqual('version=1', graph_url_v1.query)

            res = client.get('/graphs/%s' % id)
            self.assertEqual(
                json.loads(res.get_data(as_text=True))[
                    'features'][0]['names'][0]['toponym'],
                'Minnesooooooota')

            res = client.get('/graphs/%s?version=0' % id)
            self.assertEqual(
                json.loads(res.get_data(as_text=True))[
                    'features'][0]['names'][0]['toponym'],
                'Minnesota')

            res = client.get('/graphs/%s?version=1' % id)
            self.assertEqual(
                json.loads(res.get_data(as_text=True))[
                    'features'][0]['names'][0]['toponym'],
                'Minnesooooooota')

    def test_delete_graph(self):
        with open(filepath('test-graph.json')) as f:
            graph_json = f.read()
        with self.client as client:
            id = 'places/us-states'
            res = client.put(
                '/graphs/%s' % id,
                data=graph_json,
                content_type='application/json',
                headers={'Authorization': 'Bearer '
                         + 'ZjdjNjQ1ODQtMDc1MC00Y2I2LThjODEtMjkzMmY1ZGFhYmI4'})
            self.assertEqual(res.status_code, http.client.CREATED)
            res = client.delete(
                '/graphs/%s' % id,
                buffered=True,
                headers={'Authorization': 'Bearer '
                         + 'ZjdjNjQ1ODQtMDc1MC00Y2I2LThjODEtMjkzMmY1ZGFhYmI4'})
            self.assertEqual(res.status_code, http.client.NO_CONTENT)
            res = client.get('/graphs/%s' % id)
            self.assertEqual(res.status_code, http.client.NOT_FOUND)
            res = client.get('/graphs/%s?version=0' % id)
            self.assertEqual(res.status_code, http.client.OK)
            res = client.get('/graphs/')
            self.assertEqual(res.status_code, http.client.OK)
            data = json.loads(res.get_data(as_text=True))
            self.assertEqual(
                {'http://localhost.localdomain:5000/d/'},
                set(data['graphs'].keys()))
            res = client.put(
                '/graphs/%s' % id,
                data=graph_json,
                content_type='application/json',
                headers={'Authorization': 'Bearer '
                         + 'ZjdjNjQ1ODQtMDc1MC00Y2I2LThjODEtMjkzMmY1ZGFhYmI4'})
            self.assertEqual(res.status_code, http.client.CREATED)
            graph_url_v1 = urlparse(res.headers['Location'])
            self.assertEqual('/graphs/%s' % id, graph_url_v1.path)
            self.assertEqual('version=1', graph_url_v1.query)
            res = client.get('/graphs/%s' % id)
            self.assertEqual(res.status_code, http.client.OK)
            res = client.get('/graphs/%s?version=0' % id)
            self.assertEqual(res.status_code, http.client.OK)
            res = client.get('/graphs/%s?version=1' % id)
            self.assertEqual(res.status_code, http.client.OK)

    def test_group_sibling_graphs(self):
        with open(filepath('test-graph.json')) as f:
            graph_json = f.read()
        with self.client as client:
            res = client.put(
                '/graphs/places/A',
                data=graph_json,
                content_type='application/json',
                headers={'Authorization': 'Bearer '
                         + 'ZjdjNjQ1ODQtMDc1MC00Y2I2LThjODEtMjkzMmY1ZGFhYmI4'})
            self.assertEqual(res.status_code, http.client.CREATED)
            res = client.put(
                '/graphs/places/B',
                data=graph_json,
                content_type='application/json',
                headers={'Authorization': 'Bearer '
                         + 'ZjdjNjQ1ODQtMDc1MC00Y2I2LThjODEtMjkzMmY1ZGFhYmI4'})
            self.assertEqual(res.status_code, http.client.CREATED)
            res = client.get('/graphs/places/')
            self.assertEqual(res.status_code, http.client.OK)
            data = json.loads(res.get_data(as_text=True))
            self.assertEqual(
                {'http://localhost.localdomain:5000/graphs/places/A',
                 'http://localhost.localdomain:5000/graphs/places/B'},
                set(data['graphs'].keys()))
