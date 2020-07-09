import re
import random
from copy import deepcopy
from itertools import chain
from jsonpatch import JsonPatch

PREFIX = 'p0'  # shoulder assigned by EZID service
XDIGITS = '23456789bcdfghjkmnpqrstvwxz'
AUTHORITY_SEQUENCE_LENGTH = 4
PERIOD_SEQUENCE_LENGTH = 3
IDENTIFIER_RE = re.compile(
    r'^%s[%s]{%s}(?:[%s]{1}[%s]{%s})?[%s]{1}$' % (
        PREFIX,
        XDIGITS, AUTHORITY_SEQUENCE_LENGTH,
        XDIGITS,
        XDIGITS, PERIOD_SEQUENCE_LENGTH,
        XDIGITS))
ADD_PERIOD_PATH = re.compile(
    r'^(?P<path_prefix>/authorities/(?P<authority_id>.*)/periods/)'
    + r'(.*)~1\.well-known~1genid~1(.*)$')
REPLACE_PERIODS_PATH = re.compile(
    r'^/authorities/(?P<authority_id>.*)/periods$')
ADD_AUTHORITY_PATH = re.compile(
    r'^(?P<path_prefix>/authorities/)(.*)~1\.well-known~1genid~1(.*)$')
SKOLEM_BASE = r'^(.*)/\.well-known/genid/'
SKOLEM_URI = re.compile(SKOLEM_BASE + r'(.*)$')
ASSIGNED_SKOLEM_URI = re.compile(SKOLEM_BASE + r'assigned/(?P<id>.*)$')


def for_period(authority_id):
    check(authority_id)
    return id_from_sequence(
        authority_id[len(PREFIX):] +
        random_sequence(PERIOD_SEQUENCE_LENGTH))


def for_authority():
    return id_from_sequence(
        random_sequence(AUTHORITY_SEQUENCE_LENGTH))


def prefix(s):
    if s.startswith('/'):
        return PREFIX + s[1:]
    else:
        return PREFIX + s


def unprefix(s):
    if s.startswith(PREFIX):
        return s[len(PREFIX):]
    else:
        return s


def id_from_sequence(sequence):
    return prefix(add_check_digit(sequence))


def assert_valid(identifier, strict=True):
    return check(prefix(identifier), strict)


def check(identifier, strict=True):
    if not IDENTIFIER_RE.match(identifier):
        raise IdentifierException(
            'malformed identifier: {}'.format(identifier))
    sequence = identifier[len(PREFIX):-1]
    check_digit = check_digit_for(sequence)
    if check_digit == identifier[-1]:
        return

    if not strict:
        # Identifiers minted for periods in the initial data load had their
        # checksums calculated in a different way (a `/` was inserted
        # between the authority and period IDs to form the sequence),
        # so check for that variation as well.
        old_check_digit = OLD_check_digit_for(sequence)
        if old_check_digit == identifier[-1]:
            return

    raise IdentifierException(
        ('Malformed identifier: {}' +
         ' (check digit was {} but should have been {})').format(
             identifier, identifier[-1], check_digit))


def random_sequence(length):
    return ''.join(random.choice(XDIGITS) for x in range(length))


def add_check_digit(sequence):
    return sequence + check_digit_for(sequence)


def ordinal_value(char):
    try:
        return XDIGITS.index(char)
    except ValueError:
        return 0


# from http://search.cpan.org/~jak/Noid/noid#NOID_CHECK_DIGIT_ALGORITHM
def check_digit_for(sequence):
    total = sum([ordinal_value(char) * position
                 for position, char in enumerate(sequence, start=1)])
    return XDIGITS[total % len(XDIGITS)]


def OLD_check_digit_for(sequence):
    if len(sequence) > AUTHORITY_SEQUENCE_LENGTH:
        authority_id = sequence[:-PERIOD_SEQUENCE_LENGTH]
        period_id = sequence[-PERIOD_SEQUENCE_LENGTH:]
        return check_digit_for('%s/%s' % (authority_id, period_id))

    return check_digit_for(sequence)


def index_by_id(items):
    return {i['id']: i for i in items}


def replace_skolem_ids(
        patch_or_obj,
        dataset,
        removed_entity_keys,
        dataset_id_map):

    patch_id_map = {}

    existing_ids = set([unprefix(key) for key in removed_entity_keys])
    if (len(dataset) > 0):
        existing_ids |= set(chain.from_iterable(
            ([cid] + list(c['periods'].keys())
             for cid, c in dataset['authorities'].items())))

    def unused_identifier(id_generator, *args):
        for i in range(10):
            new_id = id_generator(*args)
            if new_id not in existing_ids:
                return new_id
        raise IdentifierException(
            'Too many identifier collisions:'
            + ' {} existing ids'.format(len(existing_ids)))

    def deskolemize(skolem_uri, id_generator, *args):
        match = ASSIGNED_SKOLEM_URI.match(skolem_uri)
        if match:  # patch for initial load, keep assigned IDs
            permanent_id = match.group('id')
            if permanent_id in existing_ids:
                raise IdentifierException(
                    'ID collision on ' + permanent_id)
        elif SKOLEM_URI.match(skolem_uri):
            existing_id = dataset_id_map.get(skolem_uri, None)
            if existing_id is not None:
                raise IdentifierException(
                    'Skolem ID is already mapped to ' + existing_id)
            permanent_id = unused_identifier(id_generator, *args)
        else:
            raise IdentifierException(
                'Non-skolem ID for new entity: ' + skolem_uri)
        patch_id_map[skolem_uri] = permanent_id
        existing_ids.add(permanent_id)
        return permanent_id

    def assign_period_id(period, authority_id):
        period['id'] = deskolemize(
            period['id'], for_period, authority_id)
        return period

    def assign_authority_ids(authority):
        authority['id'] = deskolemize(authority['id'], for_authority)
        authority['periods'] = index_by_id(
            [assign_period_id(d, authority['id'])
             for d in authority['periods'].values()])
        return authority

    def modify_operation(op):
        new_op = deepcopy(op)

        m = ADD_PERIOD_PATH.match(op['path'])
        if m and op['op'] == 'add':
            # adding a new period to an authority
            authority_id = m.group('authority_id')
            new_op['value'] = assign_period_id(
                new_op['value'], authority_id)
            new_op['path'] = m.group('path_prefix') + new_op['value']['id']
            return new_op

        m = REPLACE_PERIODS_PATH.match(op['path'])
        if m and op['op'] in ['add', 'replace']:
            # replacing all periods in an authority
            authority_id = m.group('authority_id')
            new_op['value'] = index_by_id(
                [assign_period_id(d, authority_id)
                 for d in new_op['value'].values()])
            return new_op

        m = ADD_AUTHORITY_PATH.match(op['path'])
        if m and op['op'] == 'add':
            # adding new authority
            new_op['value'] = assign_authority_ids(new_op['value'])
            new_op['path'] = m.group('path_prefix') + new_op['value']['id']
            return new_op

        if (op['path'] == '/authorities'
                and op['op'] in ['add', 'replace']):
            # replacing all authorities
            new_op['value'] = index_by_id(
                [assign_authority_ids(c) for c in new_op['value'].values()])
            return new_op

        return new_op

    def is_skolem_uri(v):
        if not isinstance(v, str):
            return False
        if ASSIGNED_SKOLEM_URI.match(v):
            return True
        if SKOLEM_URI.match(v):
            return True
        return False

    def replace_skolem_values(d):
        for k, v in d.items():
            if isinstance(v, dict):
                d[k] = replace_skolem_values(v)
            elif isinstance(v, list):
                d[k] = [patch_id_map[i] if is_skolem_uri(i) else i for i in v]
            elif is_skolem_uri(v):
                d[k] = patch_id_map[v]
        return d

    if hasattr(patch_or_obj, 'patch'):
        ops = [modify_operation(op) for op in patch_or_obj]
        result = JsonPatch([replace_skolem_values(op) for op in ops])
    else:
        result = deepcopy(patch_or_obj)
        result['authorities'] = replace_skolem_values(index_by_id(
            [assign_authority_ids(c)
             for c in patch_or_obj['authorities'].values()]))

    return result, patch_id_map


class IdentifierException(Exception):
    pass


if __name__ == "__main__":
    from sys import argv
    import json
    for filename in argv[1:]:
        with open(filename) as f:
            i = json.load(f)
            o = replace_skolem_ids(i, i)
            print(json.dumps(o))
