import json
from datetime import datetime
from uuid import UUID
from werkzeug.routing import BaseConverter
from rdflib import Graph
from pygments import highlight
from pygments.lexers import TurtleLexer, JsonLexer
from pygments.formatters import HtmlFormatter


def isoformat(value):
    return datetime.utcfromtimestamp(value).isoformat() + '+00:00'


def jsonld_to_turtle(jsonld):
    return Graph().parse(data=json.dumps(jsonld), format='json-ld')\
                  .serialize(format='turtle')


def highlight_string(string, lexer):
    return highlight(string, lexer, HtmlFormatter(
        full=True, style='colorful', linenos='table', lineanchors='line'))


def highlight_ttl(ttl):
    return highlight_string(ttl, TurtleLexer())


def highlight_json(data):
    return highlight_string(
        json.dumps(data, sort_keys=True, indent=2), JsonLexer())


class UUIDConverter(BaseConverter):

    def to_python(self, s):
        return UUID(s)

    def to_url(self, uuid):
        return str(uuid)
