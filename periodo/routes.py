import json
import random
import requests
import string
from io import StringIO
from flask import request, make_response, redirect, url_for, session, abort
from periodo import app, database, identifier, auth, utils
from urllib.parse import urlencode
from werkzeug.http import http_date


if app.config['HTML_REPR_EXISTS']:
    @app.route('/images/<path:path>')
    @app.route('/periodo-client.js')
    @app.route('/periodo-client-<path:path>.js')
    @app.route('/favicon.ico')
    @app.route('/index.html')
    def static_proxy(path=None):
        return app.send_static_file('html' + request.path)


def get_mimetype():
    if request.accept_mimetypes.best == 'application/json':
        return 'json'
    if request.accept_mimetypes.best == 'application/ld+json':
        return 'jsonld'
    if request.accept_mimetypes.best == 'text/turtle':
        return 'ttl'
    return None


@app.route('/h', endpoint='history')
def see_history():
    mimetype = get_mimetype()
    if mimetype is None:
        url = url_for('index', _anchor='history')
    else:
        url = url_for('history-%s' % mimetype,  **request.args)
    return redirect(url, code=303)


@app.route('/v', endpoint='vocab')
@app.route('/v', endpoint='vocabulary')
def vocab():
    if request.accept_mimetypes.best == 'text/turtle':
        return redirect(url_for('vocab_as_turtle'), code=303)
    else:
        return redirect(url_for('vocab_as_html'), code=303)


@app.route('/v.ttl')
def vocab_as_turtle():
    return app.send_static_file('vocab.ttl')


@app.route('/v.ttl.html')
def vocab_as_html():
    return app.send_static_file('vocab.html')


# http://www.w3.org/TR/void/#well-known
@app.route('/.well-known/void', endpoint='description')
@app.route('/.well-known/void.ttl')
# N2T resolver strips hyphens so handle this too
@app.route('/.wellknown/void')
@app.route('/.wellknown/void.ttl')
def void():
    if request.accept_mimetypes.best == 'text/html':
        return redirect(url_for('void_as_html'), code=303)
    return make_response(database.get_dataset()['description'], 200, {
        'Content-Type': 'text/turtle',
        'Link': '</>; rel="alternate"; type="text/html"',
    })


@app.route('/.well-known/void.ttl.html')
@app.route('/.wellknown/void.ttl.html')
def void_as_html():
    ttl = database.get_dataset()['description']
    return make_response(utils.highlight_ttl(ttl), 200, {
        'Content-Type': 'text/html',
        'Link': '</>; rel="alternate"; type="text/html"',
    })


# URIs for abstract resources (no representations, just 303 See Other)
@app.route('/d', endpoint='abstract_dataset')
def see_dataset():
    return redirect(url_for('dataset', **request.args), code=303)


@app.route('/<string(length=%s):collection_id>'
           % (identifier.COLLECTION_SEQUENCE_LENGTH + 1))
def see_collection(collection_id):
    mimetype = get_mimetype()
    if mimetype is None:
        url = url_for('index', _anchor=request.path[1:])
    else:
        url = url_for('collection-%s' % mimetype, collection_id=collection_id,
                      **request.args)
    return redirect(url, code=303)


@app.route('/<string(length=%s):definition_id>'
           % (identifier.COLLECTION_SEQUENCE_LENGTH + 1 +
              identifier.DEFINITION_SEQUENCE_LENGTH + 1))
def see_definition(definition_id):
    mimetype = get_mimetype()
    if mimetype is None:
        url = url_for('index', _anchor=request.path[1:])
    else:
        url = url_for('definition-%s' % mimetype, definition_id=definition_id,
                      **request.args)
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
        'https://orcid.org/oauth/token',
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


@app.route('/export.sql')
def export():
    sql = StringIO()
    database.dump(sql)
    response = make_response(sql.getvalue(), 200, {
        'Content-Type':
        'text/plain',
        'Content-Disposition':
        'attachment; filename="periodo-export-{}.sql"'.format(http_date())
    })
    sql.close()
    return response
