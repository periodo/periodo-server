from datetime import datetime, timezone
from flask import request, url_for
from periodo import app, identifier
from urllib.parse import urlencode


def absolute_url(base, endpoint, **kwargs):
    if app.config['CANONICAL']:
        return (base + identifier.prefix(url_for(endpoint, **kwargs)))
    else:
        return url_for(endpoint, _external=True, **kwargs)


def isoformat(posix_timestamp):
    return datetime.fromtimestamp(posix_timestamp, tz=timezone.utc).isoformat()


def isoparse(iso_timestamp):
    return datetime.fromisoformat(iso_timestamp).timestamp()


def build_client_url(page, **values):
    return '%s/?%s' % (
        app.config['CLIENT_URL'],
        urlencode(dict(page=page,
                       backendID='web-%s' % request.url_root,
                       **values))
    )
