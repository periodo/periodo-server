import json
import random
import httpx
import string
from flask import (
    request,
    make_response,
    redirect,
    url_for,
    session,
    abort,
    Response,
    stream_with_context,
    escape,
)
from periodo import app, database, identifier, auth, highlight
from urllib.parse import urlencode
from werkzeug.http import http_date
from periodo.feed import generate_activity_feed
from periodo.utils import build_client_url


def get_mimetype():
    if request.accept_mimetypes.best == "application/json":
        return "json"
    if request.accept_mimetypes.best == "application/ld+json":
        return "jsonld"
    if request.accept_mimetypes.best == "text/turtle":
        return "ttl"
    if request.accept_mimetypes.best == "application/n-triples":
        return "nt"
    return None


@app.route("/h.ttl", endpoint="history-ttl")
def legacy_history_endpoint_redirect():
    return redirect(url_for("history-short-nt", **request.args), code=301)


@app.route("/h", endpoint="history")
def see_history():
    mimetype = get_mimetype()
    if mimetype is None:
        url = build_client_url(page="backend-history")
    else:
        url = url_for("history-short-nt", **request.args)
    return redirect(url, code=303)


@app.route("/v", endpoint="vocabulary")
def vocab():
    if request.accept_mimetypes.best == "text/turtle":
        return redirect("v.ttl", code=303)
    else:
        return redirect("v.ttl.html", code=303)


@app.route("/client-packages/", endpoint="client-packages")
def client_packages():
    abort(404)  # this is served by nginx


# http://www.w3.org/TR/void/#well-known
@app.route("/.well-known/void", endpoint="description")
@app.route("/.well-known/void.ttl")
# N2T resolver strips hyphens so handle this too
@app.route("/.wellknown/void")
@app.route("/.wellknown/void.ttl")
def void():
    if request.accept_mimetypes.best == "text/html":
        return redirect(url_for("void_as_html"), code=303)
    return make_response(
        database.get_dataset()["description"],
        200,
        {
            "Content-Type": "text/turtle",
            "Link": '</>; rel="alternate"; type="text/html"',
        },
    )


@app.route("/.well-known/void.ttl.html")
@app.route("/.wellknown/void.ttl.html")
def void_as_html():
    ttl = database.get_dataset()["description"]
    return make_response(
        highlight.as_turtle(ttl),
        200,
        {
            "Content-Type": "text/html; charset=utf-8",
            "Link": '</>; rel="alternate"; type="text/html"',
        },
    )


# URIs for abstract resources (no representations, just 303 See Other)
@app.route("/d", endpoint="abstract_dataset")
def see_dataset():
    return redirect(url_for("dataset-short", **request.args), code=303)


@app.route(
    "/<string(length=%s):authority_id>" % (identifier.AUTHORITY_SEQUENCE_LENGTH + 1),
    endpoint="authority",
)
def see_authority(authority_id):
    try:
        identifier.assert_valid(authority_id, strict=False)
    except identifier.IdentifierException:
        return abort(404)

    mimetype = get_mimetype()
    if mimetype is None:
        url = build_client_url(
            page="authority-view", authorityID=identifier.prefix(authority_id)
        )
    else:
        url = url_for(
            "authority-%s" % mimetype, authority_id=authority_id, **request.args
        )

    return redirect(url, code=303)


@app.route(
    "/<string(length=%s):period_id>"
    % (
        identifier.AUTHORITY_SEQUENCE_LENGTH + 1 + identifier.PERIOD_SEQUENCE_LENGTH + 1
    ),
    endpoint="period",
)
def see_period(period_id):
    try:
        identifier.assert_valid(period_id, strict=False)
    except identifier.IdentifierException:
        return abort(404)

    mimetype = get_mimetype()
    if mimetype is None:
        periodID = request.path[1:]
        authorityID = periodID[0 : identifier.AUTHORITY_SEQUENCE_LENGTH + 1]
        url = build_client_url(
            page="period-view",
            authorityID=identifier.prefix(authorityID),
            periodID=identifier.prefix(periodID),
        )
    else:
        url = url_for("period-%s" % mimetype, period_id=period_id, **request.args)

    return redirect(url, code=303)


def generate_state_token():
    return "".join(
        random.choice(string.ascii_uppercase + string.digits) for _ in range(32)
    )


def build_redirect_uri(request_args):
    if "cli" in request_args:
        return url_for("registered", cli=True, _external=True)
    else:
        kwargs = {}
        if "origin" in request_args:
            kwargs["origin"] = request_args["origin"]
        return url_for("registered", _external=True, **kwargs)


@app.route("/register")
def register():
    state_token = generate_state_token()
    session["state_token"] = state_token
    params = {
        "client_id": app.config["ORCID_CLIENT_ID"],
        "redirect_uri": build_redirect_uri(request.args),
        "response_type": "code",
        "scope": "/authenticate",
        "state": state_token,
    }
    return redirect("https://orcid.org/oauth/authorize?{}".format(urlencode(params)))


@app.route("/registered")
def registered():
    if not request.args["state"] == session.pop("state_token", None):
        abort(403)
    data = {
        "client_id": app.config["ORCID_CLIENT_ID"],
        "client_secret": app.config["ORCID_CLIENT_SECRET"],
        "code": request.args["code"],
        "grant_type": "authorization_code",
        "redirect_uri": build_redirect_uri(request.args),
        "scope": "/authenticate",
    }
    response = httpx.post(
        "https://orcid.org/oauth/token",
        headers={"Accept": "application/json"},
        data=data,
    )
    if not response.status_code == 200:
        data.pop("client_secret", None)
        app.logger.error("Response to request for ORCID credential was not OK")
        app.logger.error("Request: %s", data)
        app.logger.error("Response: %s", response.text)
    user = auth.add_user_or_update_credentials(response.json())
    if "cli" in request.args:
        return make_response(
            (
                "Your token is: {}".format(user.b64token.decode()),
                {"Content-Type": "text/plain"},
            )
        )
    else:
        return make_response(
            """
        <!doctype html>
        <head>
            <script type="text/javascript">
            opener.postMessage(
              {{ name: {}, token: {} }},
              "{}"
            )
            </script>
        </head>
        <body>
        """.format(
                json.dumps(user.name),
                json.dumps(user.b64token.decode()),
                escape(request.args.get("origin", app.config["CLIENT_URL"])),
            )
        )


@app.route("/export.sql")
def export():
    def generate():
        for line in database.dump():
            if not line.startswith('INSERT INTO "user"'):
                yield "%s\n" % line

    return Response(
        stream_with_context(generate()),
        status=200,
        headers={
            "Content-Type": "text/plain",
            "Content-Disposition": 'attachment; filename="periodo-export-{}.sql"'.format(
                http_date()
            ),
        },
    )


@app.route("/feed.xml")
def feed():
    activity_feed = generate_activity_feed()
    if activity_feed is None:
        return abort(404)
    return make_response(
        activity_feed,
        200,
        {
            "Content-Type": "application/atom+xml",
        },
    )
