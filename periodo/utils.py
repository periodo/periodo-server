from datetime import datetime
from flask import url_for
from periodo import app, identifier


def absolute_url(base, endpoint, **kwargs):
    if app.config['CANONICAL']:
        return (base + identifier.prefix(url_for(endpoint, **kwargs)))
    else:
        return url_for(endpoint, _external=True, **kwargs)


def isoformat(value):
    return datetime.utcfromtimestamp(value).isoformat() + '+00:00'
