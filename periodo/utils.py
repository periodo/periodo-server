import json
import re
import subprocess
import tempfile
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


def run_subprocess(command_line, input=None):
    app.logger.debug('Running subprocess:\n%s' % ' '.join(command_line))
    process = subprocess.run(
        command_line,
        input=input,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        encoding='utf8',
        env={'JVM_ARGS': '-Xms256M -Xmx512M'}
    )
    app.logger.debug('stdout ------------------------------------------------')
    app.logger.debug(process.stdout)
    app.logger.debug('stderr ------------------------------------------------')
    app.logger.debug(process.stderr)
    app.logger.debug('end output --------------------------------------------')
    return (process.stdout, process.stderr)


def triples_to_csv(data_path):
    return run_subprocess(
        [app.config['ARQ'],
         '--data', data_path,
         '--query', app.config['CSV_QUERY'],
         '--results=CSV'],
    )


def jsonld_to(serialization, jsonld):
    return run_subprocess(
        [app.config['RIOT'],
         '--syntax=jsonld',
         '--formatted=%s' % serialization],
        input=json.dumps(jsonld)
    )


class RDFTranslationError(Exception):
    def __init__(self, message='RDF translation failed; please contact us!\n'):
        super().__init__(message)


def looks_like(serialization, data):
    # checking the return code is not reliable, because riot/arq will return 1
    # even if there are only warnings. So we look at the first character of
    # output as a hint
    if len(data) == 0:
        return False
    if serialization == 'ttl':
        return data[0] == '@'  # @prefix
    if serialization == 'csv':
        return data[0] == 'p'  # period
    if serialization == 'nt':
        return (data[0] == '<' or data[0] == '_')  # URI or blank node
    return False


def log_error(stdout, stderr):
    app.logger.error('stdout:\n%s' % stdout)
    app.logger.error('stderr:\n%s' % stderr)


def jsonld_to_turtle(jsonld):
    turtle, errors = jsonld_to('ttl', jsonld)
    if not looks_like('ttl', turtle):
        log_error(turtle, errors)
        raise RDFTranslationError()
    return turtle


def jsonld_to_csv(jsonld):
    triples, errors = jsonld_to('nt', jsonld)
    if not looks_like('nt', triples):
        log_error(triples, errors)
        raise RDFTranslationError()

    with tempfile.NamedTemporaryFile(suffix='.nt', delete=False) as data:
        data.write(triples.encode())
        data.flush()

        csv, errors = triples_to_csv(data.name)
        if not looks_like('csv', csv):
            log_error(csv, errors)
            raise RDFTranslationError()
        return csv


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
