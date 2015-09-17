import json
import random
import requests
import string
from flask import request, make_response, redirect, url_for, session, abort
from periodo import app, database, provenance, identifier, auth
from urllib.parse import urlencode

if app.config['HTML_REPR_EXISTS']:
    @app.route('/lib/<path:path>')
    @app.route('/dist/<path:path>')
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


@app.route('/register')
def register():
    state_token = generate_state_token()
    session['state_token'] = state_token
    params = {
        'client_id': app.config['ORCID_CLIENT_ID'],
        'redirect_uri': url_for('registered', _external=True),
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
        'redirect_uri': url_for('registered', _external=True),
        'scope': '/authenticate',
    }
    response = requests.post(
        'https://pub.orcid.org/oauth/token',
        headers={'Accept': 'application/json'},
        allow_redirects=True, data=data)
    credentials = response.json()
    if not response.status_code == 200:
        app.logger.error('Response to request for ORCID credentials was not OK')
        app.logger.error(response.text)
    identity = auth.add_user_or_update_credentials(credentials)
    database.get_db().commit()
    return make_response(
        """
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
