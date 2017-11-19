import os
from flask import Flask, request
from flask_principal import Principal
from flask_restful import Api
from periodo.secrets import SECRET_KEY, ORCID_CLIENT_ID, ORCID_CLIENT_SECRET
from periodo.utils import UUIDConverter

app = Flask(__name__)
app.secret_key = SECRET_KEY
app.url_map.converters['uuid'] = UUIDConverter
principal = Principal(app, use_sessions=False)

app.config.update(
    DATABASE='./db.sqlite',
    ORCID_CLIENT_ID=ORCID_CLIENT_ID,
    ORCID_CLIENT_SECRET=ORCID_CLIENT_SECRET,
    # HTML representation of root resource is optional and dependent on the
    # existence of a folder in static/html containing an index.html file.
    HTML_REPR_EXISTS=os.path.exists(os.path.join(
        os.path.dirname(__file__),
        'static',
        'html',
        'index.html'))
)

if not app.debug:
    import platform
    socket = None
    if (platform.system() == 'Linux'):
        socket = '/dev/log'
    elif (platform.system() == 'Darwin'):
        socket = '/var/run/syslog'
    if socket:
        import logging
        from logging.handlers import SysLogHandler
        handler = SysLogHandler(address=socket)
        handler.setLevel(logging.WARNING)
        handler.setFormatter(
            logging.Formatter('%(name)s: [%(levelname)s] %(message)s'))
        app.logger.addHandler(handler)


@app.after_request
def add_cors_headers(response):
    response.headers.add('Access-Control-Allow-Origin', '*')
    response.headers.add('Access-Control-Allow-Headers', 'If-Modified-Since')
    response.headers.add('Access-Control-Expose-Headers', 'Last-Modified')
    return response

# end app setup ---------------------------------------------------------------

import periodo.auth


class PeriodOApi(Api):
    def handle_error(self, e):
        response = periodo.auth.handle_auth_error(e)
        if response is None:
            return super().handle_error(e)
        else:
            return response

    def make_response(self, data, *args, **kwargs):
        # Override content negotation for content-type-specific URLs.
        if request.path.endswith('.json'):
            res = self.representations[
                'application/json'](data, *args, **kwargs)
            res.content_type = 'application/json'
            return res
        if request.path.endswith('.jsonld'):
            res = self.representations[
                'application/json'](data, *args, **kwargs)
            res.content_type = 'application/ld+json'
            return res
        return super().make_response(data, *args, **kwargs)

api = PeriodOApi(app)


@principal.identity_loader
def load_identity():
    return periodo.auth.load_identity_from_authorization_header()

# end api setup ---------------------------------------------------------------

import periodo.routes
import periodo.representations
import periodo.resources
