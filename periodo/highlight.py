import json
import re
from pygments import highlight
from pygments.lexers import TurtleLexer, JsonLexer
from pygments.formatters import HtmlFormatter


def as_string(s, lexer):
    return highlight(s, lexer, LinkifiedHtmlFormatter(
        full=True, style='colorful', linenos='table', lineanchors='line'))


def as_turtle(s):
    return as_string(s, TurtleLexer())


def as_json(s):
    return as_string(json.dumps(s, indent=2, sort_keys=True), JsonLexer())


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