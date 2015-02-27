import re
import random
from copy import deepcopy
from itertools import chain

from jsonpatch import JsonPatch

PREFIX = 'p0' # shoulder assigned by EZID service
XDIGITS = '23456789bcdfghjkmnpqrstvwxz'
COLLECTION_SEQUENCE_LENGTH = 4
DEFINITION_SEQUENCE_LENGTH = 3
IDENTIFIER_RE = re.compile(
    r'^%s[%s]{%s}([%s]{1}[%s]{%s})?[%s]{1}$' % (
        PREFIX,
        XDIGITS, COLLECTION_SEQUENCE_LENGTH,
        XDIGITS,
        XDIGITS, DEFINITION_SEQUENCE_LENGTH,
        XDIGITS))

def for_definition(collection_id):
    check(collection_id)
    return id_from_sequence(
        collection_id[len(PREFIX):] +
        random_sequence(DEFINITION_SEQUENCE_LENGTH))
    
def for_collection():
    return id_from_sequence(
        random_sequence(COLLECTION_SEQUENCE_LENGTH))

def prefix(s):
    return PREFIX + s

def id_from_sequence(sequence):
    return prefix(add_check_digit(sequence))

def check(identifier):
    if not IDENTIFIER_RE.match(identifier):
        raise IdentifierException('malformed identifier: {}'.format(identifier))
    check_digit = check_digit_for(identifier[len(PREFIX):-1])
    if not check_digit == identifier[-1]:
        raise IdentifierException(
            ('malformed identifier: {}' +
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
    total = sum([ ordinal_value(char) * position
                  for position, char in enumerate(sequence, start=1) ])
    return XDIGITS[total % len(XDIGITS)]


ADD_DEFINITION_PATH = re.compile(
    r'^(?P<path_prefix>/periodCollections/(?P<collection_id>.*)/definitions/)(.*)~1\.well-known~1genid~1(.*)$')
REPLACE_DEFINITIONS_PATH = re.compile(
    r'^/periodCollections/(?P<collection_id>.*)/definitions$')
ADD_COLLECTION_PATH = re.compile(
    r'^(?P<path_prefix>/periodCollections/)(.*)~1\.well-known~1genid~1(.*)$')
SKOLEM_URI = re.compile(r'^(.*)/\.well-known/genid/(.*)$')

def index_by_id(items):
    return { i['id']:i for i in items }

def replace_skolem_ids(patch_or_obj, dataset):

    existing_ids = set(chain.from_iterable(
        ( [cid] + list(c['definitions'].keys())
          for cid,c in dataset['periodCollections'].items() )))

    def unused_identifier(id_generator, *args):
        for i in range(10):
            new_id = id_generator(*args)
            if new_id not in existing_ids:
                existing_ids.add(new_id)
                return new_id
        raise IdentifierException(
            'Too many identifier collisions:'
            + ' {} existing ids'.format(len(existing_ids)))

    def assign_definition_id(definition, collection_id):
        if SKOLEM_URI.match(definition['id']):
            definition['id'] = unused_identifier(for_definition, collection_id)
        return definition

    def assign_collection_ids(collection):
        if SKOLEM_URI.match(collection['id']):
            collection['id'] = unused_identifier(for_collection)
        collection['definitions'] = index_by_id(
            [ assign_definition_id(d, collection['id'])
              for d in collection['definitions'].values() ]) 
        return collection

    def modify_operation(op):
        new_op = deepcopy(op)

        m = ADD_DEFINITION_PATH.match(op['path'])
        if m and op['op'] == 'add':
            # adding a new definition to a collection
            collection_id = m.group('collection_id')
            new_op['value'] = assign_definition_id(new_op['value'], collection_id)
            new_op['path'] = m.group('path_prefix') + new_op['value']['id']
            return new_op

        m = REPLACE_DEFINITIONS_PATH.match(op['path'])
        if m and op['op'] in ['add','replace']:
            # replacing all definitions in a collection
            collection_id = m.group('collection_id')
            new_op['value'] = index_by_id(
                [ assign_definition_id(d, collection_id) for d in new_op['value'].values() ])
            return new_op
        
        m = ADD_COLLECTION_PATH.match(op['path'])
        if m and op['op'] == 'add':
            # adding new collection
            new_op['value'] = assign_collection_ids(new_op['value'])
            new_op['path'] = m.group('path_prefix') + new_op['value']['id']
            return new_op
        
        if op['path'] == '/periodCollections' and op['op'] in ['add','replace']:
            # replacing all collections
            new_op['value'] = index_by_id(
                [ assign_collection_ids(c) for c in new_op['value'].values() ])
            return new_op

        return new_op

    if hasattr(patch_or_obj, 'patch'):
        return JsonPatch([ modify_operation(op) for op in patch_or_obj ])
    else:
        out = deepcopy(patch_or_obj)
        out['periodCollections'] = index_by_id(
            [ assign_collection_ids(c)
              for c in patch_or_obj['periodCollections'].values() ])
        return out

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
