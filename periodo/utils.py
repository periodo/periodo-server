import json
import re
from datetime import datetime
from uuid import UUID
from flask import url_for
from werkzeug.routing import BaseConverter
from rdflib import ConjunctiveGraph
from pygments import highlight
from pygments.lexers import TurtleLexer, JsonLexer
from pygments.formatters import HtmlFormatter
from periodo import identifier


def absolute_url(app, context, endpoint, **kwargs):
    if app.config['CANONICAL']:
        return (context['@base']
                + identifier.prefix(url_for(endpoint, **kwargs)))
    else:
        return url_for(endpoint, _external=True, **kwargs)


def isoformat(value):
    return datetime.utcfromtimestamp(value).isoformat() + '+00:00'


def jsonld_to_turtle(jsonld):
    g = ConjunctiveGraph()
    g.parse(data=json.dumps(jsonld), format='json-ld')
    return g.serialize(format='turtle')


def highlight_string(string, lexer):
    return highlight(string, lexer, LinkifiedHtmlFormatter(
        full=True, style='colorful', linenos='table', lineanchors='line'))


def highlight_ttl(ttl):
    return highlight_string(ttl, TurtleLexer())


def highlight_json(data):
    return highlight_string(
        json.dumps(data, indent=2, sort_keys=True), JsonLexer())


class UUIDConverter(BaseConverter):

    def to_python(self, s):
        return UUID(s)

    def to_url(self, uuid):
        return str(uuid)


# match URL values in Pygmented JSON or TTL HTML output
pattern = re.compile(
    r'(<span class="(?:s2|nv)">&(?:quot|lt);)' +
    r'(https?://[^&]+)' +
    r'(&(?:quot|gt);</span>)'
)


class LinkifiedHtmlFormatter(HtmlFormatter):

    def _linkify(self, source):
        for i, t in source:
            if i == 1:
                yield i, pattern.sub(r'\1<a href="\2">\2</a>\3', t)
            else:
                yield i, t

    def wrap(self, source, outfile):
        return self._wrap_div(self._wrap_pre(self._linkify(source)))
