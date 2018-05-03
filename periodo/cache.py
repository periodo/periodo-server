LONG_TIME = 31557600  # 1 year - versioned reprs that should not change
MEDIUM_TIME = 604800  # 1 week - slow-to-generate reprs that change infreq.
SHORT_TIME = 86400    # 1 day - derived reprs like TTL and HTML


def set_max_age(response, max_age):
    if 'Cache-Control' not in response.headers:
        response.headers['Cache-Control'] = (
            'public, max-age={}'.format(max_age))
    return response


def long_time(response):
    return set_max_age(response, LONG_TIME)


def medium_time(response):
    return set_max_age(response, MEDIUM_TIME)


def short_time(response):
    return set_max_age(response, SHORT_TIME)


def no_time(response):
    return set_max_age(response, 0)
