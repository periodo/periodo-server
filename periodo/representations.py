import json
from flask import request, make_response, redirect, url_for
from periodo import app, api, routes, utils


def context_url(context):
    if app.config['CANONICAL']:
        return context['@base'] + 'p0c'
    else:
        return url_for('context', _external=True)


def abbreviate_context(data):
    if ((data is None
         or '@context' not in data
         or len(data) == 1
         or type(data['@context']) is list)):

        # don't abbreviate non-LD responses, the context object itself, or bags
        return data

    context = data['@context']

    if '__inline' in context:
        context.pop('__inline', None)
        context.pop('__version', None)
        data['@context'] = context
    else:
        data['@context'] = [
            context_url(context),
            {'@base': context['@base']}
        ]
        if '__version' in context:
            data['@context'][0] += '?version=%s' % context['__version']

    return data


@api.representation('text/html')
def output_html(data, code, headers=None):
    if app.config['HTML_REPR_EXISTS'] and request.path == '/':
        res = app.send_static_file('html/index.html')
    elif request.path == '/d/':
        res = redirect('/d.jsonld', code=307)
    elif request.path == '/c':
        res = redirect('/c.json.html', code=307)
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
        res = make_response(utils.jsonld_to_turtle(data), code)
    res.headers.extend(headers or {})
    return res


@api.representation('application/json')
def output_json(data, code, headers=None):
    res = make_response(
        json.dumps(abbreviate_context(data)) + '\n', code)
    res.headers.extend(headers or {})
    return res


@api.representation('application/ld+json')
def output_jsonld(data, code, headers=None):
    return output_json(data, code, headers)


@api.representation('text/turtle+html')
def output_turtle_as_html(data, code, headers=None):
    ttl = utils.jsonld_to_turtle(data)
    res = make_response(utils.highlight_ttl(ttl), code)
    res.headers.extend(headers or {})
    return res


@api.representation('application/json+html')
def output_json_as_html(data, code, headers=None):
    res = make_response(
        utils.highlight_json(abbreviate_context(data)), code)
    res.headers.extend(headers or {})
    return res
