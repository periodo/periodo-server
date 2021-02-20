import os
import json
import rdflib
import logging
import subprocess
from uuid import UUID
from logging.config import dictConfig
from flask import Flask, request
from flask_principal import Principal
from flask_restful import Api
from werkzeug.http import http_date
from werkzeug.routing import BaseConverter
from periodo.middleware import RemoveTransferEncodingHeaderMiddleware

DEV_SERVER_NAME = 'localhost.localdomain:5000'

# Allow running tests without access to periodo.secrets
try:
    from periodo.secrets import (
        SECRET_KEY, ORCID_CLIENT_ID, ORCID_CLIENT_SECRET)
except ModuleNotFoundError as e:
    if 'TESTING' in os.environ:
        SECRET_KEY, ORCID_CLIENT_ID, ORCID_CLIENT_SECRET = 'xxx', 'xxx', 'xxx'
    else:
        raise e

# Disable normalization of literals because rdflib handles gYears improperly:
# https://github.com/RDFLib/rdflib/issues/806
rdflib.NORMALIZE_LITERALS = False

# Silence rdflib warnings
logging.getLogger('rdflib.term').setLevel(logging.ERROR)


class UUIDConverter(BaseConverter):

    def to_python(self, s):
        return UUID(s)

    def to_url(self, uuid):
        return str(uuid)


# configure logging
if not os.environ.get('TESTING', False):
    dictConfig({
        'version': 1,
        'formatters': {'default': {
            'format': '%(name)s: [%(levelname)s] %(message)s',
        }},
        'handlers': {'wsgi': {
            'class': 'logging.StreamHandler',
            'stream': 'ext://flask.logging.wsgi_errors_stream',
            'formatter': 'default'
        }},
        'root': {
            'level': 'DEBUG',
            'handlers': ['wsgi']
        }
    })

app = Flask(__name__)
app.secret_key = SECRET_KEY
app.url_map.converters['uuid'] = UUIDConverter
principal = Principal(app, use_sessions=False)

# When receiving requests with the HTTP header 'Transfer-Encoding: chunked',
# the combination of nginx + uwsgi somehow adds a (correct) 'Content-Length'
# header but does not remove the 'Transfer-Encoding' header. But these two
# headers are incompatible and confuse werkzeug, so we remove the
# 'Transfer-Encoding' header with this middleware.
app.wsgi_app = RemoveTransferEncodingHeaderMiddleware(app.wsgi_app)


def locate_bin(name, envvar):
    path = os.environ.get(envvar)
    if path is not None:
        return path
    try:
        res = subprocess.check_output('which ' + name, shell=True)
        return res.decode('utf-8').strip()
    except Exception:
        app.logger.error(
            f'Could not find binary for `{name}`. Either include this binary'
            + f' in your PATH, or set the environment variable {envvar}')
        return '/usr/local/bin/' + name


app.config.update(
    DATABASE=os.environ.get('DATABASE', './db.sqlite'),
    CACHE=os.environ.get('CACHE', None),
    RIOT=locate_bin('riot', 'RIOT'),
    ARQ=locate_bin('arq', 'ARQ'),
    CSV_QUERY=os.environ.get('CSV_QUERY', './periods-as-csv.rq'),
    SERVER_NAME=os.environ.get('SERVER_NAME', DEV_SERVER_NAME),
    CLIENT_URL=os.environ.get('CLIENT_URL', 'https://client.perio.do'),
    CANONICAL=json.loads(os.environ.get('CANONICAL', 'false')),
    ORCID_CLIENT_ID=ORCID_CLIENT_ID,
    ORCID_CLIENT_SECRET=ORCID_CLIENT_SECRET
)
app.logger.info('finished app configuration')


@app.after_request
def add_date_header(response):
    response.headers.add('Date', http_date())
    return response


CORS_ALLOWED_HEADERS = [
    'If-Modified-Since',
    'Authorization',
    'Content-Type',
]

CORS_ALLOWED_METHODS = [
    'GET',
    'POST',
    'PATCH',
    'HEAD',
    'OPTIONS',
]

CORS_EXPOSED_HEADERS = [
    'Last-Modified',
    'Location',
    'Link',
    'X-Total-Count',
    'X-PeriodO-Server-Version',
]


@app.after_request
def add_cors_headers(response):
    response.headers.add('Access-Control-Allow-Origin', '*')
    response.headers.add('Access-Control-Allow-Headers',
                         ', '.join(CORS_ALLOWED_HEADERS))
    response.headers.add('Access-Control-Expose-Headers',
                         ', '.join(CORS_EXPOSED_HEADERS))
    response.headers.add('Access-Control-Allow-Methods',
                         ', '.join(CORS_ALLOWED_METHODS))
    return response


# end app setup ---------------------------------------------------------------

import periodo.auth  # noqa: E402


SUFFIXES = {
    '.json': 'application/json',
    '.jsonld': 'application/ld+json',
    '.ttl': 'text/turtle',
    '.json.html': 'application/json+html',
    '.jsonld.html': 'application/json+html',
    '.ttl.html': 'text/turtle+html',
    '.nt': 'application/n-triples',
    '.csv': 'text/csv',
}


class PeriodOApi(Api):
    def handle_error(self, e):
        response = periodo.auth.handle_auth_error(e)
        if response is None:
            return super().handle_error(e)
        else:
            return response

    def make_response(self, data, *args, **kwargs):
        # Override content negotation for content-type-specific URLs.
        for suffix, content_type in SUFFIXES.items():
            if request.path.endswith(suffix):
                return self.representations[content_type](
                    data, *args, **kwargs)
        return super().make_response(data, *args, **kwargs)


api = PeriodOApi(app)


@principal.identity_loader
def load_identity():
    return periodo.auth.load_identity_from_authorization_header()


# end api setup ---------------------------------------------------------------

import periodo.routes           # noqa: E402
import periodo.representations  # noqa: E402
import periodo.resources        # noqa: E402
