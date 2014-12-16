import re
import random
from copy import deepcopy
from itertools import chain

from jsonpatch import JsonPatch

XDIGITS = '23456789bcdfghjkmnpqrstvwxz'
COLLECTION_ID_LENGTH = 4
DEFINITION_ID_LENGTH = 3
IDENTIFIER_RE = re.compile(
    r'[%s]{%s}(/[%s]{%s})?' % (XDIGITS, COLLECTION_ID_LENGTH,
                               XDIGITS, DEFINITION_ID_LENGTH))

def for_definition(collection_id):
    check(collection_id)
    return add_check_digit(
        '/'.join([ collection_id, random_sequence(DEFINITION_ID_LENGTH) ]))
    
def for_collection():
    return add_check_digit(random_sequence(COLLECTION_ID_LENGTH))

def check(identifier):
    check_digit = check_digit_for(identifier[:-1])
    if not check_digit == identifier[-1]:
        raise IdentifierException(
            ('malformed identifier: {}' +
             ' (check digit was {} but should have been {})').format(
                 identifier, identifier[-1], check_digit))

def random_sequence(length):
    return ''.join(random.choice(XDIGITS) for x in range(length))

def add_check_digit(identifier):
    return identifier + check_digit_for(identifier)

def ordinal_value(char):
    try:
        return XDIGITS.index(char)
    except ValueError:
        return 0

# from http://search.cpan.org/~jak/Noid/noid#NOID_CHECK_DIGIT_ALGORITHM
def check_digit_for(identifier):
    if not IDENTIFIER_RE.match(identifier):
        raise IdentifierException('malformed identifier: {}'.format(identifier))
    total = sum([ ordinal_value(char) * position
                  for position, char in enumerate(identifier, start=1) ])
    return XDIGITS[total % len(XDIGITS)]


ADD_DEFINITION_PATH = re.compile(
    r'^(?P<path_prefix>/periodCollections/(?P<collection_id>.*)/definitions/)(.*)~1\.well-known~1genid~1(.*)$')
REPLACE_DEFINITIONS_PATH = re.compile(
    r'^/periodCollections/(?P<collection_id>.*)/definitions$')
ADD_COLLECTION_PATH = re.compile(
    r'^(?P<path_prefix>/periodCollections/)(.*)~1\.well-known~1genid~1(.*)$')
SKOLEM_URI = re.compile(r'^(.*)/\.well-known/genid/(.*)$')

def replace_skolem_ids(patch, data):

    existing_ids = chain.from_iterable(
        ( [cid] + list(c['definitions'].keys())
          for cid,c in data['periodCollections'].items() ))

    def unused_identifier(id_generator, *args):
        for i in range(10):
            new_id = id_generator(*args)
            if new_id not in existing_ids:
                return new_id
        raise IdentifierException(
            'Too many identifier collisions:'
            + ' {} existing ids'.format(len(existing_ids)))

    def index_by_id(items):
        return { i['id']:i for i in items }
    
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
            new_op['path'] = m.group('path_prefix') + new_op['value']['id'].replace('/', '~1')
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
            
    return JsonPatch([ modify_operation(op) for op in patch ])

class IdentifierException(Exception):
    pass


