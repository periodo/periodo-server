import httpx
from periodo import app
from typing import Tuple
from werkzeug.routing import Rule

LONG_TIME = 31557600  # 1 year - versioned reprs that should not change
MEDIUM_TIME = 604800  # 1 week - slow-to-generate reprs that change infreq.
SHORT_TIME = 86400  # 1 day  - derived reprs like TTL and HTML


def set_max_age(response, max_age, server_only):
    # X-Accel-Expires is only for nginx; Cache-Control is for all HTTP caches
    if server_only:
        if "X-Accel-Expires" not in response.headers:
            response.headers["X-Accel-Expires"] = max_age
        if "Cache-Control" not in response.headers:
            response.headers["Cache-Control"] = "public, max-age=0"
    else:
        if "Cache-Control" not in response.headers:
            response.headers["Cache-Control"] = "public, max-age={}".format(max_age)

    return response


def long_time(response, server_only=False):
    return set_max_age(response, LONG_TIME, server_only)


def medium_time(response, server_only=False):
    return set_max_age(response, MEDIUM_TIME, server_only)


def short_time(response, server_only=False):
    return set_max_age(response, SHORT_TIME, server_only)


def no_time(response, server_only=False):
    return set_max_age(response, 0, server_only)


def purge(keys: list[str]) -> None:
    cache_purger = app.config["CACHE_PURGER_URL"]
    if cache_purger is not None:
        try:
            response = httpx.post(cache_purger, json=keys)
            response.raise_for_status()
        except httpx.HTTPError as e:
            app.logger.error(f"Cache purge failed: {e}")


def DEFAULT_KEY(r: Rule) -> str:
    return r.rule


def purge_endpoint(endpoint: str, key=DEFAULT_KEY, params: Tuple[str, ...] = ()):
    keys = [key(r) for r in app.url_map.iter_rules() if r.endpoint.startswith(endpoint)]
    purge(keys)
    for p in params:
        purge(["{}?{}".format(k, p) for k in keys])


def purge_history() -> None:
    purge_endpoint("history", params=("full",))


def purge_dataset() -> None:
    purge_endpoint("dataset", params=("inline-context",))


def purge_graphs() -> None:
    purge_endpoint("graphs")


def subpaths(path: str) -> list[str]:
    if path == "":
        return []
    end = -2 if path.endswith("/") else -1
    return [path] + subpaths(path[0 : path.rfind("/", 0, end) + 1])


def purge_graph(graph_id: str) -> None:
    for path in subpaths(graph_id):

        def key(r: Rule, path: str = path):
            return r.rule.replace("<path:id>", path)

        purge_endpoint("graph", key=key)
