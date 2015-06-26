import os
from flask import Flask, request
from flask.ext.principal import Principal
from flask.ext.restful import Api
from periodo.secrets import SECRET_KEY, ORCID_CLIENT_ID, ORCID_CLIENT_SECRET

app = Flask(__name__)
app.secret_key = SECRET_KEY
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
