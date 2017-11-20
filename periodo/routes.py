import json
import random
import requests
import string
from flask import request, make_response, redirect, url_for, session, abort
from periodo import app, database, provenance, identifier, auth
from urllib.parse import urlencode

if app.config['HTML_REPR_EXISTS']:
    @app.route('/images/<path:path>')
    @app.route('/periodo-client.js')
    @app.route('/periodo-client-<path:path>.js')
    @app.route('/favicon.ico')
    @app.route('/index.html')
    def static_proxy(path=None):
        return app.send_static_file('html' + request.path)


@app.route('/h')
def history():
    return make_response(
        provenance.history(), 200, {'Content-Type': 'application/ld+json'})


@app.route('/v')
def vocab():
    return app.send_static_file('vocab.ttl')


# http://www.w3.org/TR/void/#well-known
@app.route('/.well-known/void')
# N2T resolver strips hyphens so handle this too
@app.route('/.wellknown/void')
def void():
    return make_response(database.get_dataset()['description'], 200, {
        'Content-Type': 'text/turtle',
        'Link': '</>; rel="alternate"; type="text/html"',
    })


# URIs for abstract resources (no representations, just 303 See Other)
@app.route('/d', endpoint='abstract_dataset')
def see_dataset():
    return redirect(url_for('dataset', **request.args), code=303)


@app.route('/<string(length=%s):collection_id>'
           % (identifier.COLLECTION_SEQUENCE_LENGTH + 1))
def see_collection(collection_id):
    if request.accept_mimetypes.best == 'application/json':
        url = url_for('collection-json', collection_id=collection_id,
                      **request.args)
    elif request.accept_mimetypes.best == 'application/ld+json':
        url = url_for('collection-jsonld', collection_id=collection_id,
                      **request.args)
    else:
        url = url_for('index', _anchor=request.path[1:])
    return redirect(url, code=303)


@app.route('/<string(length=%s):definition_id>'
           % (identifier.COLLECTION_SEQUENCE_LENGTH + 1 +
              identifier.DEFINITION_SEQUENCE_LENGTH + 1))
def see_definition(definition_id):
    if request.accept_mimetypes.best == 'application/json':
        url = url_for('definition-json', definition_id=definition_id,
                      **request.args)
    elif request.accept_mimetypes.best == 'application/ld+json':
        url = url_for('definition-jsonld', definition_id=definition_id,
                      **request.args)
    else:
        url = url_for('index', _anchor=request.path[1:])
    return redirect(url, code=303)


def generate_state_token():
    return ''.join(random.choice(string.ascii_uppercase + string.digits)
                   for x in range(32))


def build_redirect_uri(cli=False):
    if cli:
        return url_for('registered', cli=True, _external=True)
    else:
        return url_for('registered', _external=True)


@app.route('/register')
def register():
    state_token = generate_state_token()
    session['state_token'] = state_token
    params = {
        'client_id': app.config['ORCID_CLIENT_ID'],
        'redirect_uri': build_redirect_uri(cli=('cli' in request.args)),
        'response_type': 'code',
        'scope': '/authenticate',
        'state': state_token,
    }
    return redirect(
        'https://orcid.org/oauth/authorize?{}'.format(urlencode(params)))


@app.route('/registered')
def registered():
    if not request.args['state'] == session.pop('state_token'):
        abort(403)
    data = {
        'client_id': app.config['ORCID_CLIENT_ID'],
        'client_secret': app.config['ORCID_CLIENT_SECRET'],
        'code': request.args['code'],
        'grant_type': 'authorization_code',
        'redirect_uri': build_redirect_uri(cli=('cli' in request.args)),
        'scope': '/authenticate',
    }
    response = requests.post(
        'https://pub.orcid.org/oauth/token',
        headers={'Accept': 'application/json'},
        allow_redirects=True, data=data)
    if not response.status_code == 200:
        app.logger.error('Response to request for ORCID credential was not OK')
        app.logger.error('Request: %s', data)
        app.logger.error('Response: %s', response.text)
    credentials = response.json()
    if 'name' not in credentials or len(credentials['name']) == 0:
        # User has made their name private, so just use their ORCID as name
        credentials['name'] = credentials['orcid']
    identity = auth.add_user_or_update_credentials(credentials)
    database.get_db().commit()
    if 'cli' in request.args:
        return make_response(
            ('Your token is: {}'.format(identity.b64token.decode()),
             {'Content-Type': 'text/plain'}))
    else:
        return make_response("""
        <!doctype html>
        <head>
            <script type="text/javascript">
            localStorage.auth = '{}';
            window.close();
            </script>
        </head>
        <body>
        """.format(json.dumps(
            {'name': credentials['name'], 'token': identity.b64token.decode()}
        )))
