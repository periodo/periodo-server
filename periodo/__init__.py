import os
import re
import json
import rdflib
import logging
from uuid import UUID
from logging.config import dictConfig
from flask_principal import Principal, identity_loaded
from flask import Flask, make_response, g, request
from werkzeug.exceptions import NotFound
from werkzeug.http import http_date
from werkzeug.middleware.proxy_fix import ProxyFix
from werkzeug.routing import BaseConverter
from periodo.middleware import RemoveTransferEncodingHeaderMiddleware

DEV_SERVER_NAME = "localhost.localdomain:5000"

SECRETS = {"SECRET_KEY": "xxx", "ORCID_CLIENT_ID": "xxx", "ORCID_CLIENT_SECRET": "xxx"}
if "TESTING" not in os.environ:
    for secret in SECRETS.keys():
        value = os.environ.get(secret)
        if value is None:
            raise Exception(f"{secret} is not set")
        else:
            SECRETS[secret] = value

# Disable normalization of literals because rdflib handles gYears improperly:
# https://github.com/RDFLib/rdflib/issues/806
rdflib.NORMALIZE_LITERALS = False

# Silence rdflib warnings
logging.getLogger("rdflib.term").setLevel(logging.ERROR)


class UUIDConverter(BaseConverter):
    def to_python(self, s):
        return UUID(s)

    def to_url(self, uuid):
        return str(uuid)


# configure logging
if not os.environ.get("TESTING", False):
    dictConfig(
        {
            "version": 1,
            "formatters": {
                "default": {
                    "format": "%(name)s: [%(levelname)s] %(message)s",
                }
            },
            "handlers": {
                "wsgi": {
                    "class": "logging.StreamHandler",
                    "stream": "ext://flask.logging.wsgi_errors_stream",
                    "formatter": "default",
                }
            },
            "root": {"level": "INFO", "handlers": ["wsgi"]},
        }
    )

app = Flask(__name__)
app.secret_key = SECRETS["SECRET_KEY"]
app.url_map.converters["uuid"] = UUIDConverter
app.response_class.autocorrect_location_header = True  # type: ignore
principal = Principal(app, use_sessions=False)

# Flask is poorly designed and so doesn't play well with standard HTTP things
# like proxies. So we have to add this ridiculous "proxy fix" middleware.
app.wsgi_app = ProxyFix(app.wsgi_app, x_for=1, x_proto=1)

# When receiving requests with the HTTP header 'Transfer-Encoding: chunked',
# the combination of nginx + uwsgi somehow adds a (correct) 'Content-Length'
# header but does not remove the 'Transfer-Encoding' header. But these two
# headers are incompatible and confuse werkzeug, so we remove the
# 'Transfer-Encoding' header with this middleware.
app.wsgi_app = RemoveTransferEncodingHeaderMiddleware(app.wsgi_app)

app.config.update(
    DATABASE=os.environ.get("DATABASE", "./db.sqlite"),
    CACHE_PURGER_URL=os.environ.get("CACHE_PURGER_URL", None),
    CSV_QUERY=os.environ.get("CSV_QUERY", "./periods-as-csv.rq"),
    SERVER_NAME=os.environ.get("SERVER_NAME", DEV_SERVER_NAME),
    SERVER_VERSION=os.environ.get(
        "SERVER_VERSION", os.environ.get("SERVER_VERSION", "development")
    ),
    CLIENT_URL=os.environ.get("CLIENT_URL", "https://client.staging.perio.do"),
    CANONICAL=json.loads(os.environ.get("CANONICAL", "false")),
    ORCID_CLIENT_ID=SECRETS["ORCID_CLIENT_ID"],
    ORCID_CLIENT_SECRET=SECRETS["ORCID_CLIENT_SECRET"],
    TRANSLATION_SERVICE=os.environ.get(
        "TRANSLATION_SERVICE", "http://periodo-translator-dev.flycast"
    ),
)
app.logger.info("finished app configuration")


@app.after_request
def add_date_header(response):
    response.headers.add("Date", http_date())
    return response


CORS_ALLOWED_HEADERS = [
    "If-Modified-Since",
    "Authorization",
    "Content-Type",
]

CORS_ALLOWED_METHODS = [
    "GET",
    "POST",
    "PATCH",
    "HEAD",
    "OPTIONS",
]

CORS_EXPOSED_HEADERS = [
    "Last-Modified",
    "Location",
    "Link",
    "X-Total-Count",
    "X-PeriodO-Server-Version",
]


@app.after_request
def add_cors_headers(response):
    response.headers.add("Access-Control-Allow-Origin", "*")
    response.headers.add(
        "Access-Control-Allow-Headers", ", ".join(CORS_ALLOWED_HEADERS)
    )
    response.headers.add(
        "Access-Control-Expose-Headers", ", ".join(CORS_EXPOSED_HEADERS)
    )
    response.headers.add(
        "Access-Control-Allow-Methods", ", ".join(CORS_ALLOWED_METHODS)
    )
    return response


@app.after_request
def add_server_version_header(response):
    response.headers.add("X-PeriodO-Server-Version", app.config["SERVER_VERSION"])
    return response


# end app setup ---------------------------------------------------------------

import periodo.auth  # noqa: E402
import periodo.database  # noqa: E402
import periodo.highlight  # noqa: E402


@app.errorhandler(NotFound)
def handle_not_found_error(_):
    sanitized_path = re.sub(r"[^./a-z0-9]", r"", request.path[1:], flags=re.IGNORECASE)
    message = {
        "code": 404,
        "status": "Not Found",
        "message": f"{sanitized_path} is not a valid PeriodO identifier. Perhaps you followed a broken link?",
    }
    if request.accept_mimetypes.best == "application/json":
        return make_response(
            json.dumps(message),
            404,
            {"Content-Type": "application/json"},
        )
    else:
        return make_response(periodo.highlight.as_json(message), 404)


@app.errorhandler(periodo.auth.AuthenticationFailed)
def handle_auth_failed_error(e):
    parts = ['Bearer realm="PeriodO"']
    if e.error:
        parts.append('error="{}"'.format(e.error))
    if e.error_description:
        parts.append('error_description="{}"'.format(e.error_description))
    if e.error_uri:
        parts.append('error_uri="{}"'.format(e.error_uri))
    app.logger.debug("authentication failed: " + (", ".join(parts)))
    return make_response(
        e.error_description or "", 401, {"WWW-Authenticate": ", ".join(parts)}
    )


@app.errorhandler(periodo.auth.PermissionDenied)
def handle_permission_denied_error(_):
    description = "The access token does not provide sufficient privileges"
    app.logger.debug(description)
    return make_response(
        description,
        403,
        {
            "WWW-Authenticate": 'Bearer realm="PeriodO", error="insufficient_scope", '
            + "error_description="
            + '"The access token does not provide sufficient privileges", '
            + 'error_uri="http://tools.ietf.org/html/rfc6750#section-6.2.3"'
        },
    )


@principal.identity_loader
def load_identity():
    return periodo.auth.load_identity_from_authorization_header()


@identity_loaded.connect_via(app)
def on_identity_loaded(_, identity):
    if identity.id is not None:
        g.user = periodo.database.get_user(identity.id)


# end api setup ---------------------------------------------------------------

import periodo.routes  # noqa: E402
import periodo.representations  # noqa: E402
import periodo.resources  # noqa: E402
