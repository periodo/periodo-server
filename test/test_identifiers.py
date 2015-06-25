import os
import json
import identifier
import unittest
from jsonpatch import JsonPatch
from .filepath import filepath


class TestIdentifiers(unittest.TestCase):

    def test_substitution_error(self):
        def substitute(s):
            chars = list(s)
            chars[2] = identifier.XDIGITS[
                (identifier.XDIGITS.index(chars[2]) + 1)
                % len(identifier.XDIGITS)]
            return ''.join(chars)

        cid = identifier.for_collection()
        identifier.check(cid)
        cid2 = substitute(cid)
        with self.assertRaises(identifier.IdentifierException):
            identifier.check(cid2)

        did = identifier.for_definition(cid)
        identifier.check(did)
        did2 = substitute(did)
        with self.assertRaises(identifier.IdentifierException):
            identifier.check(did2)

    def test_transposition_error(self):
        def transpose(s):
            chars = list(s)
            for i in range(-3, -(len(s)+1), -1):
                if not chars[i] == chars[i+1]:
                    chars[i], chars[i+1] = chars[i+1], chars[i]
                    return ''.join(chars)

        cid = identifier.for_collection()
        identifier.check(cid)
        cid2 = transpose(cid)
        with self.assertRaises(identifier.IdentifierException):
            identifier.check(cid2)

        did = identifier.for_definition(cid)
        identifier.check(did)
        did2 = transpose(did)
        with self.assertRaises(identifier.IdentifierException):
            identifier.check(did2)

    def test_id_has_wrong_shape(self):
        with self.assertRaises(identifier.IdentifierException):
            identifier.check('p06rw8')  # collection id too short
        with self.assertRaises(identifier.IdentifierException):
            identifier.check('p06rw87/669p')  # definition id has slash

    def test_generate_definition_id(self):
        cid = identifier.for_collection()
        did = identifier.for_definition(cid)
        self.assertTrue(did.startswith(cid))
        self.assertEqual(len(did), 11)

    def test_replace_skolem_ids_when_adding_items(self):
        with open(filepath('test-data.json')) as f:
            data = json.load(f)
        with open(filepath('test-patch-adds-items.json')) as f:
            original_patch = JsonPatch(json.load(f))
        applied_patch, new_ids = identifier.replace_skolem_ids(
            original_patch, data)
        self.assertRegex(
            applied_patch.patch[0]['path'],
            r'^/periodCollections/p0trgkv/definitions/p0trgkv[%s]{4}$'
            % identifier.XDIGITS)
        self.assertRegex(
            applied_patch.patch[0]['value']['id'],
            r'^p0trgkv[%s]{4}$' % identifier.XDIGITS)
        identifier.check(applied_patch.patch[0]['value']['id'])
        self.assertTrue(applied_patch.patch[0]['value']['id'] in new_ids)

        self.assertRegex(
            applied_patch.patch[1]['path'],
            r'^/periodCollections/p0[%s]{5}$' % identifier.XDIGITS)
        self.assertRegex(
            applied_patch.patch[1]['value']['id'],
            r'^p0[%s]{5}$' % identifier.XDIGITS)
        collection_id = applied_patch.patch[1]['value']['id']
        identifier.check(collection_id)
        self.assertTrue(collection_id in new_ids)
        defs = applied_patch.patch[1]['value']['definitions']
        self.assertRegex(
            list(defs.keys())[0],
            r'^%s[%s]{4}$' % (collection_id, identifier.XDIGITS))
        self.assertEqual(
            list(defs.values())[0]['id'],
            list(defs.keys())[0])
        identifier.check(list(defs.keys())[0])

    def test_replace_skolem_ids_when_replacing_definitions(self):
        with open(filepath('test-data.json')) as f:
            data = json.load(f)
        with open(filepath('test-patch-replaces-definitions.json')) as f:
            original_patch = JsonPatch(json.load(f))
        applied_patch, new_ids = identifier.replace_skolem_ids(
            original_patch, data)
        self.assertEqual(
            applied_patch.patch[0]['path'],
            original_patch.patch[0]['path'])
        definition_id, definition = list(
            applied_patch.patch[0]['value'].items())[0]
        self.assertTrue(definition_id in new_ids)
        self.assertRegex(
            definition_id,
            r'^p0trgkv[%s]{4}$' % identifier.XDIGITS)
        self.assertEqual(definition_id, definition['id'])
        identifier.check(definition_id)

    def test_replace_skolem_ids_when_replacing_collections(self):
        with open(filepath('test-data.json')) as f:
            data = json.load(f)
        with open(filepath('test-patch-replaces-collections.json')) as f:
            original_patch = JsonPatch(json.load(f))
        applied_patch, new_ids = identifier.replace_skolem_ids(
            original_patch, data)
        self.assertEqual(
            applied_patch.patch[0]['path'],
            original_patch.patch[0]['path'])

        collection_id, collection = list(
            applied_patch.patch[0]['value'].items())[0]
        self.assertTrue(collection_id in new_ids)
        self.assertRegex(
            collection_id,
            r'^p0[%s]{5}$' % identifier.XDIGITS)
        self.assertEqual(collection_id, collection['id'])
        identifier.check(collection_id)

        definition_id, definition = list(
            applied_patch.patch[0]['value'][collection_id]['definitions']
            .items())[0]
        self.assertTrue(definition_id in new_ids)
        self.assertRegex(
            definition_id,
            r'^%s[%s]{4}$' % (collection_id, identifier.XDIGITS))
        self.assertEqual(definition_id, definition['id'])
        identifier.check(definition_id)
