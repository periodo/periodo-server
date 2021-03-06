import json
import unittest
from jsonpatch import JsonPatch
from .filepath import filepath
from periodo import identifier


class TestIdentifiers(unittest.TestCase):

    def test_assert_valid_loose(self):
        # old style checksum
        identifier.assert_valid('3wskd4mmt', strict=False)
        # new style checksum
        identifier.assert_valid('jrrjb8spw', strict=False)

    def test_assert_valid_strict(self):
        with self.assertRaises(identifier.IdentifierException):
            # old style checksum
            identifier.assert_valid('3wskd4mmt')
        # new style checksum
        identifier.assert_valid('jrrjb8spw')

    def test_substitution_error(self):
        def substitute(s):
            chars = list(s)
            chars[2] = identifier.XDIGITS[
                (identifier.XDIGITS.index(chars[2]) + 1)
                % len(identifier.XDIGITS)]
            return ''.join(chars)

        cid = identifier.for_authority()
        identifier.check(cid)
        cid2 = substitute(cid)
        with self.assertRaises(identifier.IdentifierException):
            identifier.check(cid2)

        did = identifier.for_period(cid)
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

        cid = identifier.for_authority()
        identifier.check(cid)
        cid2 = transpose(cid)
        with self.assertRaises(identifier.IdentifierException):
            identifier.check(cid2)

        did = identifier.for_period(cid)
        identifier.check(did)
        did2 = transpose(did)
        with self.assertRaises(identifier.IdentifierException):
            identifier.check(did2)

    def test_id_has_wrong_shape(self):
        with self.assertRaises(identifier.IdentifierException):
            identifier.check('p06rw8')  # authority id too short
        with self.assertRaises(identifier.IdentifierException):
            identifier.check('p06rw87/669p')  # period id has slash

    def test_generate_period_id(self):
        cid = identifier.for_authority()
        did = identifier.for_period(cid)
        self.assertTrue(did.startswith(cid))
        self.assertEqual(len(did), 11)

    def test_replace_skolem_ids_when_adding_items(self):
        with open(filepath('test-data.json')) as f:
            data = json.load(f)
        with open(filepath('test-patch-adds-items.json')) as f:
            original_patch = JsonPatch(json.load(f))
        applied_patch, id_map = identifier.replace_skolem_ids(
            original_patch, data, [], {})
        self.assertRegex(
            applied_patch.patch[0]['path'],
            r'^/authorities/p0trgkv/periods/p0trgkv[%s]{4}$'
            % identifier.XDIGITS)
        self.assertRegex(
            applied_patch.patch[0]['value']['id'],
            r'^p0trgkv[%s]{4}$' % identifier.XDIGITS)
        identifier.check(applied_patch.patch[0]['value']['id'])
        self.assertTrue(
            applied_patch.patch[0]['value']['id'] in id_map.values())

        self.assertRegex(
            applied_patch.patch[1]['path'],
            r'^/authorities/p0[%s]{5}$' % identifier.XDIGITS)
        self.assertRegex(
            applied_patch.patch[1]['value']['id'],
            r'^p0[%s]{5}$' % identifier.XDIGITS)
        authority_id = applied_patch.patch[1]['value']['id']
        identifier.check(authority_id)
        self.assertTrue(authority_id in id_map.values())
        periods = applied_patch.patch[1]['value']['periods']
        for key in periods.keys():
            self.assertRegex(
                key,
                r'^%s[%s]{4}$' % (authority_id, identifier.XDIGITS))
            self.assertEqual(
                key,
                periods[key]['id'])
            identifier.check(key)

            # check that skolem IDs in prop values get replaced too
            prop = 'broader' if 'broader' in periods[key] else 'narrower'
            self.assertRegex(
                periods[key][prop],
                r'^%s[%s]{4}$' % (authority_id, identifier.XDIGITS))
            identifier.check(periods[key][prop])
            self.assertTrue(periods[key][prop] in id_map.values())

            # check that skolem IDs in prop value arrays get replaced too
            for period_id in periods[key].get('derivedFrom', []):
                self.assertRegex(
                    period_id,
                    r'^%s[%s]{4}$' % ('p0trgkv', identifier.XDIGITS))
                identifier.check(period_id)
                self.assertTrue(period_id in id_map.values())

    def test_replace_skolem_ids_when_replacing_periods(self):
        with open(filepath('test-data.json')) as f:
            data = json.load(f)
        with open(filepath('test-patch-replaces-periods.json')) as f:
            original_patch = JsonPatch(json.load(f))
        applied_patch, id_map = identifier.replace_skolem_ids(
            original_patch, data, [], {})
        self.assertEqual(
            applied_patch.patch[0]['path'],
            original_patch.patch[0]['path'])
        period_id, period = list(
            applied_patch.patch[0]['value'].items())[0]
        self.assertTrue(period_id in id_map.values())
        self.assertRegex(
            period_id,
            r'^p0trgkv[%s]{4}$' % identifier.XDIGITS)
        self.assertEqual(period_id, period['id'])
        identifier.check(period_id)

    def test_replace_skolem_ids_when_replacing_authorities(self):
        with open(filepath('test-data.json')) as f:
            data = json.load(f)
        with open(filepath('test-patch-replaces-authorities.json')) as f:
            original_patch = JsonPatch(json.load(f))
        applied_patch, id_map = identifier.replace_skolem_ids(
            original_patch, data, [], {})
        self.assertEqual(
            applied_patch.patch[0]['path'],
            original_patch.patch[0]['path'])

        authority_id, authority = list(
            applied_patch.patch[0]['value'].items())[0]
        self.assertTrue(authority_id in id_map.values())
        self.assertRegex(
            authority_id,
            r'^p0[%s]{5}$' % identifier.XDIGITS)
        self.assertEqual(authority_id, authority['id'])
        identifier.check(authority_id)

        period_id, period = list(
            applied_patch.patch[0]['value'][authority_id]['periods']
            .items())[0]
        self.assertTrue(period_id in id_map.values())
        self.assertRegex(
            period_id,
            r'^%s[%s]{4}$' % (authority_id, identifier.XDIGITS))
        self.assertEqual(period_id, period['id'])
        identifier.check(period_id)
