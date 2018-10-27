import json
from urllib.parse import urlencode
from flask import request, make_response, redirect, url_for
from periodo import api, cache, routes, utils


def abbreviate_context(data):
    # don't abbreviate...
    if ((data is None or                     # empty responses,
         '@context' not in data or           # non-LD responses,
         '@base' not in data['@context'] or  # external LD graphs,
         len(data) == 1 or                   # the context object itself,
         type(data['@context']) is list)):   # or already-abbreviated contexts.

        return data

    context = data['@context']
    base = context['@base']

    if '__inline' in context:
        # keep context inline as requested
        context.pop('__inline', None)
        context.pop('__version', None)
        data['@context'] = context
    else:
        data['@context'] = [
            utils.absolute_url(base, 'context'),
            {'@base': base}
        ]
        if '__version' in context:
            data['@context'][0] += '?version=%s' % context['__version']

    return data


def html_version(path):
    if path == '/':
        return 'index.json.html'
    elif path.endswith('.jsonpatch'):
        return path.replace('.jsonpatch', '.json.html')
    else:
        return (path[:-1] if path.endswith('/') else path) + '.json.html'


@api.representation('text/html')
def output_html(data, code, headers={}, filename=None):
    if request.path == '/d/':
        response = redirect(
            url_for('dataset-json', version=request.args.get('version', None)),
            code=307)
    else:
        response = redirect(
            html_version(request.path) + urlencode(request.args),
            code=303)
        response.headers.add(
            'Link', '<>; rel="alternate"; type="application/json"')

    if request.path == '/':
        response.headers.add(
            'Link', '</>; rel="alternate"; type="text/turtle"; '
            + 'title="VoID description of the PeriodO Period Gazetteer')

    response.headers.extend(headers)

    return response


@api.representation('application/json')
def output_json(data, code, headers={}, filename=None):
    response = make_response(json.dumps(abbreviate_context(data)) + '\n', code)
    response.content_type = 'application/json'
    response.headers.extend(headers)

    if filename is not None:
        response.headers['Content-Disposition'] = (
            'attachment; filename="%s.json"' % filename)

    return response


@api.representation('text/turtle')
def output_turtle(data, code, headers={}, filename=None):
    if request.path == '/':
        return routes.void()

    response = make_response(utils.jsonld_to_turtle(data), code)
    response.content_type = 'text/turtle'
    response.headers.extend(headers)

    if filename is not None:
        response.headers['Content-Disposition'] = (
            'attachment; filename="%s.ttl"' % filename)

    return cache.short_time(response)


@api.representation('application/ld+json')
def output_jsonld(data, code, headers={}, filename=None):
    response = output_json(data, code, headers, filename)
    response.content_type = 'application/ld+json'

    return response


@api.representation('text/turtle+html')
def output_turtle_as_html(data, code, headers={}, filename=None):
    ttl = utils.jsonld_to_turtle(data)
    html = utils.highlight_ttl(ttl)
    response = make_response(html, code)
    response.content_type = 'text/html'
    response.headers.extend(headers)

    return cache.short_time(response)


@api.representation('application/json+html')
def output_json_as_html(data, code, headers={}, filename=None):
    json = abbreviate_context(data)
    html = utils.highlight_json(json)
    response = make_response(html, code)
    response.content_type = 'text/html'
    response.headers.extend(headers)

    return cache.short_time(response)
