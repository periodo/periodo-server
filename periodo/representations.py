import json
from flask import request, make_response
from periodo import app, api, routes


@api.representation('text/html')
def output_html(data, code, headers=None):
    if app.config['HTML_REPR_EXISTS'] and request.path == '/':
        res = app.send_static_file('html/index.html')
    else:
        res = make_response('This resource is not available as text/html', 406)
        res.headers.add('Link', '<>; rel="alternate"; type="application/json"')
    if request.path == '/':
        res.headers.add(
            'Link', '</>; rel="alternate"; type="text/turtle"; '
            + 'title="VoID description of the PeriodO Period Gazetteer')
    res.headers.extend(headers or {})
    return res


@api.representation('text/turtle')
def output_turtle(data, code, headers=None):
    if request.path == '/':
        res = routes.void()
    else:
        res = make_response(
            'This resource is not available as text/turtle', 406)
        res.headers.add('Link', '<>; rel="alternate"; type="application/json"')
    res.headers.extend(headers or {})
    return res


@api.representation('application/ld+json')
def output_jsonld(data, code, headers=None):
    res = make_response(json.dumps(data), code, headers)
    res.headers.extend(headers or {})
    return res