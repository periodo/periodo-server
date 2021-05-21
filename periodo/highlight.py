import json
import re
from pygments import highlight
from pygments.lexers.rdf import TurtleLexer
from pygments.lexers.data import JsonLexer
from pygments.formatters.html import HtmlFormatter


def as_bytes(s, lexer) -> bytes:
    table = highlight(
        s, lexer, LinkifiedHtmlFormatter(linenos="table", linespans="line")
    )
    return f"""
<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<title></title>
<link rel="stylesheet" href="/highlight-style.css">
</head>
<body>{table}</body></html>""".encode(
        "utf-8"
    )


def as_turtle(s):
    return as_bytes(s, TurtleLexer())


def as_json(s):
    return as_bytes(
        json.dumps(s, indent=2, sort_keys=True, ensure_ascii=False), JsonLexer()
    )


# match URL values in Pygmented JSON or TTL HTML output
pattern = re.compile(
    r'(<span class="(?:s2|nv)">&(?:quot|lt);)'
    + r"(https?://[^&]+)"
    + r"(&(?:quot|gt);</span>)"
)


class LinkifiedHtmlFormatter(HtmlFormatter):
    def _linkify(self, source):
        for i, t in source:
            if i == 1:
                yield i, pattern.sub(r'\1<a href="\2">\2</a>\3', t)
            else:
                yield i, t

    def wrap(self, source, _):
        return self._wrap_div(self._wrap_pre(self._linkify(source)))
