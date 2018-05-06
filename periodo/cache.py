import os
from hashlib import md5
from periodo import app

LONG_TIME = 31557600  # 1 year - versioned reprs that should not change
MEDIUM_TIME = 604800  # 1 week - slow-to-generate reprs that change infreq.
SHORT_TIME = 86400    # 1 day  - derived reprs like TTL and HTML


def set_max_age(response, max_age, server_only):
    # X-Accel-Expires is only for nginx; Cache-Control is for all HTTP caches
    if server_only:
        if 'X-Accel-Expires' not in response.headers:
            response.headers['X-Accel-Expires'] = max_age
        if 'Cache-Control' not in response.headers:
            response.headers['Cache-Control'] = 'public, max-age=0'
    else:
        if 'Cache-Control' not in response.headers:
            response.headers['Cache-Control'] = (
                'public, max-age={}'.format(max_age))

    return response


def long_time(response, server_only=False):
    return set_max_age(response, LONG_TIME, server_only)


def medium_time(response, server_only=False):
    return set_max_age(response, MEDIUM_TIME, server_only)


def short_time(response, server_only=False):
    return set_max_age(response, SHORT_TIME, server_only)


def no_time(response, server_only=False):
    return set_max_age(response, 0, server_only)


def purge(keys):
    if app.config['CACHE'] is not None:
        for key in keys:
            filename = md5(key.encode('utf-8')).hexdigest()
            path = os.path.join(  # because nginx cache_path levels=1:2
                app.config['CACHE'], filename[-1], filename[-3:-1], filename)
            try:
                if os.path.isfile(path):
                    os.remove(path)
            except OSError as e:
                app.logger.error('Failed to purge: {}'.format(key))
                app.logger.error('Error was: {}'.format(e))


def purge_endpoint(endpoint, params):
    if app.config['CACHE'] is not None:
        keys = [
            r.rule for r in app.url_map.iter_rules()
            if r.endpoint.startswith(endpoint)
        ]
        purge(keys)
        for p in params:
            purge(['{}?{}'.format(k, p) for k in keys])


def purge_history():
    purge_endpoint('history', ['full'])


def purge_dataset():
    purge_endpoint('dataset', ['inline-context'])
