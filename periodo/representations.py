import json
from typing import Optional
from urllib.parse import urlencode
from flask import make_response as flask_make_response, request, redirect
from periodo import cache, routes, utils, translate, highlight


def abbreviate_context(data):
    # don't abbreviate...
    if (
        data is None  # empty responses,
        or "@context" not in data  # non-LD responses,
        or "@base" not in data["@context"]  # external LD graphs,
        or len(data) == 1  # the context object itself,
        or type(data["@context"]) is list
    ):  # or already-abbreviated contexts

        return data

    context = data["@context"]
    base = context["@base"]

    if "__inline" in context:
        # keep context inline as requested
        context.pop("__inline", None)
        context.pop("__version", None)
        data["@context"] = context
    else:
        data["@context"] = [utils.absolute_url(base, "context-short"), {"@base": base}]
        if "__version" in context:
            data["@context"][0] += "?version=%s" % context["__version"]

    return data


def make_response(data, code=200):
    return flask_make_response(data, code)


def translation_failure(e):
    response = make_response("%s\n" % e, e.code)
    if e.code == 503:
        response.headers.add("Retry-After", 120)
    return response


def redirect_to_html(content_type, headers=None):
    if request.path == "/":
        location = f"/index.{content_type}.html"
    elif request.path.endswith(".jsonpatch"):
        location = request.path.replace(".jsonpatch", f".{content_type}.html")
    elif request.path.endswith(f".{content_type}"):
        location = f"{request.path}.html"
    else:
        path = request.path[:-1] if request.path.endswith("/") else request.path
        location = f"{path}.{content_type}.html"

    if len(request.args) > 0:
        location += f"?{urlencode(request.args)}"

    response = redirect(location, code=303)
    response.headers.add(
        "Link", f'<>; rel="alternate"; type="{SHORT_CONTENT_TYPES[content_type]}"'
    )

    if request.path == "/":
        response.headers.add(
            "Link",
            '</>; rel="alternate"; type="text/turtle"; '
            + 'title="VoID description of the PeriodO Period Gazetteer',
        )

    if headers is not None:
        response.headers.extend(headers)

    return response


def output_json(data):
    return make_response(
        json.dumps(abbreviate_context(data), ensure_ascii=False) + "\n",
    )


def output_nt(graph):
    return make_response(graph.serialize(format="nt"))


def output_turtle(data):
    if request.path == "/":
        return routes.void()

    try:
        ttl = translate.jsonld_to_turtle(data)
    except translate.RDFTranslationError as e:
        return translation_failure(e)

    return cache.short_time(make_response(ttl))


def output_csv(data):
    try:
        csv = translate.jsonld_to_csv(data)
    except translate.RDFTranslationError as e:
        return translation_failure(e)

    return cache.medium_time(make_response(csv))


def output_turtle_as_html(data):
    try:
        ttl = translate.jsonld_to_turtle(data)
        html = highlight.as_turtle(ttl)
    except translate.RDFTranslationError as e:
        return translation_failure(e)

    return cache.short_time(make_response(html))


def output_json_as_html(data):
    json = abbreviate_context(data)
    html = highlight.as_json(json)

    return cache.short_time(make_response(html))


SHORT_CONTENT_TYPES = {
    "csv": "text/csv",
    "json": "application/json",
    "json.html": "text/html; charset=utf-8",
    "jsonld": "application/ld+json",
    "jsonld.html": "text/html; charset=utf-8",
    "nt": "application/n-triples",
    "ttl": "text/turtle",
    "ttl.html": "text/html; charset=utf-8",
}


LONG_CONTENT_TYPES = {
    "application/json": "json",
    "application/json+html": "json.html",
    "application/ld+json": "jsonld",
    "application/ld+json+html": "jsonld.html",
    "application/n-triples": "nt",
    "text/csv": "csv",
    "text/html": "html",
    "text/turtle": "ttl",
    "text/turtle+html": "ttl.html",
}


REPRESENTATIONS = {
    "csv": output_csv,
    "json": output_json,
    "json.html": output_json_as_html,
    "jsonld": output_json,
    "jsonld.html": output_json_as_html,
    "nt": output_nt,
    "ttl": output_turtle,
    "ttl.html": output_turtle_as_html,
}


def get_content_type_from_request_path():
    for content_type in SHORT_CONTENT_TYPES:
        if request.path.endswith(f".{content_type}"):
            return content_type

    return None


def get_content_type_from_accept_header(supported_content_types):
    best = str(request.accept_mimetypes.best)
    content_type = LONG_CONTENT_TYPES.get(best, None)
    if content_type in supported_content_types:
        return content_type


def make_ok_response(
    data,
    supported_content_types: tuple[str, ...],
    as_html: bool = False,
    headers: dict = None,
    filename: Optional[str] = None,
):
    """Handles content negotation for resources with multiple representations.

    `supported_content_types` should be a tuple of suffixes (not
    including the `.`) representing content types supported by the
    resource.

    If the request path ends with a content-type-specific suffix, that
    will determine the content type.

    Otherwise a content type will be chosen based on the `Accept`
    header of the request.

    If no `Accept` header is present or the `Accept` header contains
    an unsupported type, the content type will default to the first
    content type supported by the resource.

    If the the `Accept` header contains `text/html` and `as_html` is
    `True`, the response will redirect to an HTMLized view of the
    selected content type.

    """
    path_type = get_content_type_from_request_path()
    accept_type = get_content_type_from_accept_header(supported_content_types)
    content_type = (
        path_type
        or accept_type
        or (supported_content_types[0] if len(supported_content_types) > 0 else "json")
    )

    if as_html and content_type == "html" and not content_type.endswith(".html"):
        return redirect_to_html(path_type or "json", headers)

    response = REPRESENTATIONS[content_type](data)
    response.content_type = SHORT_CONTENT_TYPES[content_type]

    if headers is not None:
        response.headers.extend(headers)

    if response.status_code == 200 and filename is not None:
        response.headers[
            "Content-Disposition"
        ] = f'attachment; filename="{filename}.{content_type}"'

    return response
