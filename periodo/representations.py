import json
from urllib.parse import urlencode
from flask import request, make_response, redirect, url_for
from rdflib import Graph
from periodo import api, cache, routes, utils, translate, highlight


def abbreviate_context(data):
    # don't abbreviate...
    if ((data is None                          # empty responses,
         or '@context' not in data             # non-LD responses,
         or '@base' not in data['@context']    # external LD graphs,
         or len(data) == 1                     # the context object itself,
         or type(data['@context']) is list)):  # or already-abbreviated contexts

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


def translation_failure(e):
    response = make_response('%s\n' % e, e.code)
    if (e.code == 503):
        response.headers.add('Retry-After', 120)
    return response


@api.representation('text/html')
def output_html(data, code, headers={}, filename=None):
    if request.path == '/d/':
        response = redirect(
            url_for('dataset-json', version=request.args.get('version', None)),
            code=307)
    else:
        location = html_version(request.path)
        if len(request.args) > 0:
            location += f'?{urlencode(request.args)}'
        response = redirect(location, code=303)
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
    response = make_response(
        json.dumps(abbreviate_context(data), ensure_ascii=False) + '\n',
        code
    )
    response.content_type = 'application/json'
    response.headers.extend(headers)

    if filename is not None:
        response.headers['Content-Disposition'] = (
            'attachment; filename="%s.json"' % filename)

    return response


@api.representation('application/n-triples')
def output_nt(graph, code, headers={}, filename=None):
    if not type(graph) == Graph:
        return 'n-triples representation not available'

    nt = '' if code != 200 else graph.serialize(format='nt')
    response = make_response(nt, code)
    response.content_type = 'application/n-triples'
    response.headers.extend(headers)

    if filename is not None:
        response.headers['Content-Disposition'] = (
            'attachment; filename="%s.nt"' % filename)

    return response


@api.representation('text/turtle')
def output_turtle(data, code, headers={}, filename=None):
    if request.path == '/':
        return routes.void()

    if code == 200:
        try:
            ttl = translate.jsonld_to_turtle(data)
        except translate.RDFTranslationError as e:
            return translation_failure(e)
    else:
        ttl = ''

    response = make_response(ttl, code)
    response.content_type = 'text/turtle'
    response.headers.extend(headers)

    if filename is not None:
        response.headers['Content-Disposition'] = (
            'attachment; filename="%s.ttl"' % filename)

    return cache.short_time(response)


@api.representation('text/csv')
def output_csv(data, code, headers={}, filename=None):
    if code == 200:
        try:
            csv = translate.jsonld_to_csv(data)
        except translate.RDFTranslationError as e:
            return translation_failure(e)
    else:
        csv = ''

    response = make_response(csv, code)
    response.content_type = 'text/csv'
    response.headers.extend(headers)

    if filename is not None:
        response.headers['Content-Disposition'] = (
            'attachment; filename="%s.csv"' % filename)

    return cache.medium_time(response)


@api.representation('application/ld+json')
def output_jsonld(data, code, headers={}, filename=None):
    response = output_json(data, code, headers, filename)
    response.content_type = 'application/ld+json'

    return response


@api.representation('text/turtle+html')
def output_turtle_as_html(data, code, headers={}, filename=None):
    if code == 200:
        try:
            ttl = translate.jsonld_to_turtle(data)
            html = highlight.as_turtle(ttl)
        except translate.RDFTranslationError as e:
            return translation_failure(e)
    else:
        html = ''

    response = make_response(html, code)
    response.content_type = 'text/html; charset=utf-8'
    response.headers.extend(headers)

    return cache.short_time(response)


@api.representation('application/json+html')
def output_json_as_html(data, code, headers={}, filename=None):
    json = abbreviate_context(data)
    html = highlight.as_json(json)
    response = make_response(html, code)
    response.content_type = 'text/html; charset=utf-8'
    response.headers.extend(headers)

    return cache.short_time(response)
