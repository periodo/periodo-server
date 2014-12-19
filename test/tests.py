import os
import json
import periodo
import identifier
import tempfile
import unittest
import http.client
from rdflib import Graph
from rdflib.namespace import Namespace, RDF, DCTERMS
from urllib.parse import urlparse
from flask.ext.principal import ActionNeed
from jsonpatch import JsonPatch

def setUpModule():
    os.chdir('test')

VOID = Namespace('http://rdfs.org/ns/void#')

class TestAuthentication(unittest.TestCase):

    def setUp(self):
        self.db_fd, periodo.app.config['DATABASE'] = tempfile.mkstemp()
        periodo.app.config['TESTING'] = True
        self.app = periodo.app.test_client()
        periodo.init_db()
        self.identity = periodo.add_user_or_update_credentials({
            'name': 'Testy Testerson',
            'access_token': '5005eb18-be6b-4ac0-b084-0443289b3378',
            'expires_in': 631138518,
            'orcid': '1234-5678-9101-112X',
        })
        self.expired_identity = periodo.add_user_or_update_credentials({
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
            '/dataset/',
            headers={ 'Authorization': 'Bearer ZjdlMDBjMDItNmY5Ny00NjM2LTg0OTktMDM3NDQ2ZDk1NDQ2' } )
        self.assertEqual(res.status_code, http.client.FORBIDDEN)
        self.assertEqual(
            res.headers['WWW-Authenticate'],
            'Bearer realm="PeriodO", error="insufficient_scope", '
            + 'error_description="The access token does not provide sufficient privileges", '
            + 'error_uri="http://tools.ietf.org/html/rfc6750#section-6.2.3"')

    def test_authorized_user(self):
        with self.app as client:
            res = client.patch(
                '/dataset/',
                data=self.patch,
                content_type='application/json',
                headers={ 'Authorization': 'Bearer NTAwNWViMTgtYmU2Yi00YWMwLWIwODQtMDQ0MzI4OWIzMzc4' } )
            self.assertEqual(res.status_code, http.client.ACCEPTED)
            patch_id = int(res.headers['Location'].split('/')[-2])
            creator = periodo.query_db(
                'SELECT created_by FROM patch_request WHERE id = ?',
                (patch_id,), one=True)['created_by']
            self.assertEqual(creator, 'http://orcid.org/1234-5678-9101-112X')

    def test_nonadmin_merge(self):
        res = self.app.patch(
            '/dataset/',
            data=self.patch,
            content_type='application/json',
            headers={ 'Authorization': 'Bearer NTAwNWViMTgtYmU2Yi00YWMwLWIwODQtMDQ0MzI4OWIzMzc4' } )
        res = self.app.post(
            urlparse(res.headers['Location']).path + 'merge',
            headers={ 'Authorization': 'Bearer NTAwNWViMTgtYmU2Yi00YWMwLWIwODQtMDQ0MzI4OWIzMzc4' } )
        self.assertEqual(res.status_code, http.client.FORBIDDEN)
        self.assertEqual(
            res.headers['WWW-Authenticate'],
            'Bearer realm="PeriodO", error="insufficient_scope", '
            + 'error_description="The access token does not provide sufficient privileges", '
            + 'error_uri="http://tools.ietf.org/html/rfc6750#section-6.2.3"')

    def test_admin_merge(self):
        with self.app as client:
            res = client.patch(
                '/dataset/',
                data=self.patch,
                content_type='application/json',
                headers={ 'Authorization': 'Bearer NTAwNWViMTgtYmU2Yi00YWMwLWIwODQtMDQ0MzI4OWIzMzc4' } )
            patch_id = int(res.headers['Location'].split('/')[-2])
            res = client.post(
                urlparse(res.headers['Location']).path + 'merge',
                headers={ 'Authorization': 'Bearer ZjdjNjQ1ODQtMDc1MC00Y2I2LThjODEtMjkzMmY1ZGFhYmI4' } )
            self.assertEqual(res.status_code, http.client.NO_CONTENT)
            merger = periodo.query_db(
                'SELECT merged_by FROM patch_request WHERE id = ?',
                (patch_id,), one=True)['merged_by']
            self.assertEqual(merger, 'http://orcid.org/1211-1098-7654-321X')

    def test_noncreator_patch_update(self):
        res = self.app.patch(
            '/dataset/',
            data=self.patch,
            content_type='application/json',
            headers={ 'Authorization': 'Bearer NTAwNWViMTgtYmU2Yi00YWMwLWIwODQtMDQ0MzI4OWIzMzc4' } )
        res = self.app.put(
            urlparse(res.headers['Location']).path + 'patch.jsonpatch',
            data=self.patch,
            content_type='application/json',
            headers={ 'Authorization': 'Bearer ZjdjNjQ1ODQtMDc1MC00Y2I2LThjODEtMjkzMmY1ZGFhYmI4' } )
        self.assertEqual(res.status_code, http.client.FORBIDDEN)
        self.assertEqual(
            res.headers['WWW-Authenticate'],
            'Bearer realm="PeriodO", error="insufficient_scope", '
            + 'error_description="The access token does not provide sufficient privileges", '
            + 'error_uri="http://tools.ietf.org/html/rfc6750#section-6.2.3"')

    def test_creator_patch_update(self):
        with self.app as client:
            res = client.patch(
                '/dataset/',
                data=self.patch,
                content_type='application/json',
                headers={ 'Authorization': 'Bearer NTAwNWViMTgtYmU2Yi00YWMwLWIwODQtMDQ0MzI4OWIzMzc4' } )
            res = client.put(
                urlparse(res.headers['Location']).path + 'patch.jsonpatch',
                data=self.patch,
                content_type='application/json',
                headers={ 'Authorization': 'Bearer NTAwNWViMTgtYmU2Yi00YWMwLWIwODQtMDQ0MzI4OWIzMzc4' } )
            self.assertEqual(res.status_code, http.client.OK)

    def test_update_merged_patch(self):
        with self.app as client:
            res = client.patch(
                '/dataset/',
                data=self.patch,
                content_type='application/json',
                headers={ 'Authorization': 'Bearer NTAwNWViMTgtYmU2Yi00YWMwLWIwODQtMDQ0MzI4OWIzMzc4' } )
            patch_path = urlparse(res.headers['Location']).path
            res = client.post(
                patch_path + 'merge',
                headers={ 'Authorization': 'Bearer ZjdjNjQ1ODQtMDc1MC00Y2I2LThjODEtMjkzMmY1ZGFhYmI4' } )
            res = client.put(
                patch_path + 'patch.jsonpatch',
                data=self.patch,
                content_type='application/json',
                headers={ 'Authorization': 'Bearer NTAwNWViMTgtYmU2Yi00YWMwLWIwODQtMDQ0MzI4OWIzMzc4' } )
        self.assertEqual(res.status_code, http.client.FORBIDDEN)
        self.assertEqual(
            res.headers['WWW-Authenticate'],
            'Bearer realm="PeriodO", error="insufficient_scope", '
            + 'error_description="The access token does not provide sufficient privileges", '
            + 'error_uri="http://tools.ietf.org/html/rfc6750#section-6.2.3"')

class TestPatchMethods(unittest.TestCase):

    def setUp(self):
        self.db_fd, periodo.app.config['DATABASE'] = tempfile.mkstemp()
        periodo.app.config['TESTING'] = True
        self.app = periodo.app.test_client()
        periodo.init_db()
        periodo.load_data('test-data.json')
        self.user_identity = periodo.add_user_or_update_credentials({
            'name': 'Regular Gal',
            'access_token': '5005eb18-be6b-4ac0-b084-0443289b3378',
            'expires_in': 631138518,
            'orcid': '1234-5678-9101-112X',
        })
        with open('test-patch-replace-values-1.json') as f:
            self.patch = f.read()

    def tearDown(self):
        os.close(self.db_fd)
        os.unlink(periodo.app.config['DATABASE'])

    def test_update_patch(self):
        res = self.app.patch(
            '/dataset/',
            data=self.patch,
            content_type='application/json',
            headers={ 'Authorization': 'Bearer NTAwNWViMTgtYmU2Yi00YWMwLWIwODQtMDQ0MzI4OWIzMzc4' } )
        patch_url = urlparse(res.headers['Location']).path + 'patch.jsonpatch'
        res = self.app.get(patch_url)
        res = self.app.get(patch_url)
        self.assertEqual(json.loads(self.patch),
                         json.loads(res.get_data(as_text=True)))
        with open('test-patch-replace-values-2.json') as f:
            self.patch2 = f.read()
        res = self.app.put(
            patch_url,
            data=self.patch2,
            content_type='application/json',
            headers={ 'Authorization': 'Bearer NTAwNWViMTgtYmU2Yi00YWMwLWIwODQtMDQ0MzI4OWIzMzc4' } )
        self.assertEqual(res.status_code, http.client.OK)
        res = self.app.get(patch_url)
        res = self.app.get(patch_url)
        self.assertEqual(json.loads(self.patch2),
                         json.loads(res.get_data(as_text=True)))

class TestRepresentationsAndRedirects(unittest.TestCase):

    def setUp(self):
        self.db_fd, periodo.app.config['DATABASE'] = tempfile.mkstemp()
        periodo.app.config['TESTING'] = True
        self.app = periodo.app.test_client()
        periodo.init_db()
        periodo.load_data('test-data.json')

    def tearDown(self):
        os.close(self.db_fd)
        os.unlink(periodo.app.config['DATABASE'])

    def test_dataset_description(self):
        res1 = self.app.get('', headers={ 'Accept': 'text/html' })
        self.assertEqual(res1.status_code, http.client.OK)
        self.assertEqual(res1.headers['Content-Type'], 'text/html')

        res2 = self.app.get('', headers={ 'Accept': 'text/turtle' })
        self.assertEqual(res2.status_code, http.client.OK)
        self.assertEqual(res2.headers['Content-Type'], 'text/turtle')

        g = Graph()
        g.parse(format='turtle', data=res2.get_data(as_text=True))
        desc = g.value(predicate=RDF.type, object=VOID.DatasetDescription)
        self.assertEqual(
            desc.n3(), '<http://n2t.net/ark:/58825/p0/>')
        title = g.value(subject=desc, predicate=DCTERMS.title)
        self.assertEqual(
            title.n3(), '"Description of the PeriodO Period Gazetteer"@en')

class TestIdentifiers(unittest.TestCase):

    def test_substitution_error(self):
        cid = identifier.for_collection()
        identifier.check(cid)
        chars = list(cid)
        chars[2] = chr(ord(chars[2]) + 1)
        cid2 = ''.join(chars)
        with self.assertRaises(identifier.IdentifierException):
            identifier.check(cid2)

        did = identifier.for_definition(cid)
        identifier.check(did)
        chars = list(did)
        chars[-2] = chr(ord(chars[-2]) + 1)
        did2 = ''.join(chars)
        with self.assertRaises(identifier.IdentifierException):
            identifier.check(did2)

    def test_transposition_error(self):
        cid = identifier.for_collection()
        identifier.check(cid)
        chars = list(cid)
        chars[1], chars[2] = chars[2], chars[1]
        cid2 = ''.join(chars)
        with self.assertRaises(identifier.IdentifierException):
            identifier.check(cid2)

        did = identifier.for_definition(cid)
        identifier.check(did)
        chars = list(did)
        chars[-3], chars[-2] = chars[-2], chars[-3]
        did2 = ''.join(chars)
        with self.assertRaises(identifier.IdentifierException):
            identifier.check(did2)

    def test_id_has_wrong_shape(self):
        with self.assertRaises(identifier.IdentifierException):
            identifier.check('6rw8') # collection id too short
        with self.assertRaises(identifier.IdentifierException):
            identifier.check('6rw87669p') # definition id missing slash

    def test_generate_definition_id(self):
        cid = identifier.for_collection()
        did = identifier.for_definition(cid)
        self.assertTrue(did.startswith(cid + '/'))
        self.assertEqual(len(did), 10)

    def test_replace_skolem_ids_when_adding_items(self):
        with open('test-data.json') as f:
            data = json.load(f)
        with open('test-patch-adds-items.json') as f:
            original_patch = JsonPatch(json.load(f))
        applied_patch = identifier.replace_skolem_ids(original_patch, data)
        self.assertRegex(
            applied_patch.patch[0]['path'],
            r'^/periodCollections/trgkv/definitions/trgkv~1[%s]{4}$' % identifier.XDIGITS)
        self.assertRegex(
            applied_patch.patch[0]['value']['id'],
            r'^trgkv/[%s]{4}$' % identifier.XDIGITS)
        identifier.check(applied_patch.patch[0]['value']['id'])

        self.assertRegex(
            applied_patch.patch[1]['path'],
            r'^/periodCollections/[%s]{5}$' % identifier.XDIGITS)
        self.assertRegex(
            applied_patch.patch[1]['value']['id'],
            r'^[%s]{5}$' % identifier.XDIGITS)
        collection_id = applied_patch.patch[1]['value']['id']
        identifier.check(collection_id)
        self.assertRegex(
            list(applied_patch.patch[1]['value']['definitions'].keys())[0],
            r'^%s/[%s]{4}$' % (collection_id, identifier.XDIGITS))
        self.assertEqual(
            list(applied_patch.patch[1]['value']['definitions'].values())[0]['id'],
            list(applied_patch.patch[1]['value']['definitions'].keys())[0])
        identifier.check(list(applied_patch.patch[1]['value']['definitions'].keys())[0])

    def test_replace_skolem_ids_when_replacing_definitions(self):
        with open('test-data.json') as f:
            data = json.load(f)
        with open('test-patch-replaces-definitions.json') as f:
            original_patch = JsonPatch(json.load(f))
        applied_patch = identifier.replace_skolem_ids(original_patch, data)
        self.assertEqual(
            applied_patch.patch[0]['path'],
            original_patch.patch[0]['path'])
        definition_id, definition = list(applied_patch.patch[0]['value'].items())[0]
        self.assertRegex(
            definition_id,
            r'^trgkv/[%s]{4}$' % identifier.XDIGITS)
        self.assertEqual(definition_id, definition['id'])
        identifier.check(definition_id)

    def test_replace_skolem_ids_when_replacing_collections(self):
        with open('test-data.json') as f:
            data = json.load(f)
        with open('test-patch-replaces-collections.json') as f:
            original_patch = JsonPatch(json.load(f))
        applied_patch = identifier.replace_skolem_ids(original_patch, data)
        self.assertEqual(
            applied_patch.patch[0]['path'],
            original_patch.patch[0]['path'])

        collection_id, collection = list(applied_patch.patch[0]['value'].items())[0]
        self.assertRegex(
            collection_id,
            r'^[%s]{5}$' % identifier.XDIGITS)
        self.assertEqual(collection_id, collection['id'])
        identifier.check(collection_id)

        definition_id, definition = list(applied_patch.patch[0]['value'][collection_id]['definitions'].items())[0]
        self.assertRegex(
            definition_id,
            r'^%s/[%s]{4}$' % (collection_id, identifier.XDIGITS))
        self.assertEqual(definition_id, definition['id'])
        identifier.check(definition_id)
