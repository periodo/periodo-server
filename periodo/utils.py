import json
import re
import subprocess
from datetime import datetime
from flask import url_for
from pygments import highlight
from pygments.lexers import TurtleLexer, JsonLexer
from pygments.formatters import HtmlFormatter
from periodo import app, identifier


def absolute_url(base, endpoint, **kwargs):
    if app.config['CANONICAL']:
        return (base + identifier.prefix(url_for(endpoint, **kwargs)))
    else:
        return url_for(endpoint, _external=True, **kwargs)


def isoformat(value):
    return datetime.utcfromtimestamp(value).isoformat() + '+00:00'


class RDFTranslationError(Exception):
    pass


def jsonld_to_turtle(jsonld):
    result = subprocess.run(
        [app.config['RIOT'], '--syntax=jsonld', '--formatted=ttl'],
        input=json.dumps(jsonld),
        stdout=subprocess.PIPE,
        stderr=subprocess.DEVNULL,
        encoding='utf8',
        env={'JVM_ARGS': '-Xms0M -Xmx256M'}
    )
    # checking the return code is not reliable, because riot will return 1
    # even if there are only warnings. So we look for the first character
    # of TTL output, which should be '@'
    if not (result.stdout.length > 0 and result.stdout[0] == '@'):
        raise RDFTranslationError(result.stdout)
    return result.stdout


def highlight_string(string, lexer):
    return highlight(string, lexer, LinkifiedHtmlFormatter(
        full=True, style='colorful', linenos='table', lineanchors='line'))


def highlight_ttl(ttl):
    return highlight_string(ttl, TurtleLexer())


def highlight_json(data):
    return highlight_string(
        json.dumps(data, indent=2, sort_keys=True), JsonLexer())


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
