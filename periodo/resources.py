import json
from flask import request, g, abort, url_for, redirect, Response
from flask.views import MethodView
from marshmallow import Schema, ValidationError, fields, validate
from jsonpatch import JsonPatch
from periodo import (
    app,
    cache,
    database,
    auth,
    identifier,
    patching,
    utils,
    provenance,
    representations,
)
from typing import Optional, Tuple, Type
from urllib.parse import urlencode
from webargs.flaskparser import parser
from wsgiref.handlers import format_date_time


class W3CDTF(fields.Field):
    def _serialize(self, value, attr, obj, **kwargs):
        attr, obj, kwargs  # ignored
        if value is None:
            return ""
        return utils.isoformat(value)

    def _deserialize(self, value, attr, data, **kwargs):
        attr, data, kwargs  # ignored
        try:
            return utils.isoparse(value)
        except ValueError as e:
            raise ValidationError("Invalid W3CDTF timestamp") from e


class Resource(MethodView):
    # this dummy method is replaced when the resource is registered
    def make_ok_response(self, data, headers=None, filename=None) -> Response:
        data, headers, filename
        return Response()


class ResourceError(Exception):
    def __init__(self, status, message):
        self.status = status
        self.message = message

    def response(self):
        return {"status": self.status, "message": self.message}, self.status


def parse_json(request):
    try:
        return json.loads(request.get_data(as_text=True))
    except json.JSONDecodeError:
        raise ResourceError(400, "Request data could not be parsed as JSON.")


def attach_to_dataset(o):
    if len(o) > 0:
        if app.config["CANONICAL"]:
            path = request.full_path[1:]
            if path.endswith("?"):
                path = path[:-1]
            o["primaryTopicOf"] = {
                "id": identifier.prefix(path),
                "inDataset": {
                    "id": identifier.prefix("d"),
                    "changes": identifier.prefix("h#changes"),
                },
            }
        else:
            o["primaryTopicOf"] = {
                "id": request.url,
                "inDataset": {
                    "id": url_for("abstract_dataset", _external=True),
                    "changes": url_for("history", _external=True) + "#changes",
                },
            }
    return o


def redirect_to_last_update(entity_id, version):
    if version is None:
        return None
    v = database.find_version_of_last_update(identifier.prefix(entity_id), version)
    if v is None:
        abort(404)
    if v == int(version):
        return None
    return redirect(request.path + "?version={}".format(v), code=301)


def make_dataset_url(version):
    return url_for("dataset", _external=True) + "?version=" + str(version)


def process_patch_row(row):
    d = dict(row)
    d["created_from"] = make_dataset_url(row["created_from"])
    d["applied_to"] = (
        make_dataset_url(row["created_from"]) if row["applied_to"] else None
    )
    d["identifier_map"] = (
        json.loads(row["identifier_map"]) if row["identifier_map"] else None
    )
    return d


def abort_gone_or_not_found(entity_key):
    if entity_key in database.get_removed_entity_keys():
        abort(410)
    else:
        abort(404)


def get_dataset(version=None):
    dataset = database.get_dataset(version)

    if not dataset:
        if version:
            raise ResourceError(404, "Could not find given version.")
        else:
            raise ResourceError(501, "No dataset loaded yet.")

    return dataset


HTTP_METHODS = ["get", "put", "post", "patch", "delete"]


def register_resource(
    endpoint: str,
    basepath: str,
    shortpath: Optional[str] = None,
    altpath: Optional[str] = None,
    suffixes: Tuple[str, ...] = ("json", "jsonld", "ttl", "csv"),
    register_basepath: bool = True,
    as_html: bool = False,
):
    """Adds all the necessary Flask URL routing rules for a resource.

    `endpoint` is a name that will be used to generate endpoint names
    for all routing rules.

    `basepath` is a path to which suffixes will be added to generate
    all suffixed (content-type specific) paths for the resource.

    `shortpath` is an alternative abbreviated path to which suffixes
    will be appended to generate all suffixed (content-type specific)
    paths for the resource. Defaults to `None`.

    `altpath` is an alternative path to which suffixes will *not* be
    appended. If `altpath` is specified, then the `basepath` will
    *not* be added, regardless of `register_basepath`. However,
    suffixed paths generated from `basepath` will still be
    added. Defaults to `None`.

    `suffixes` is a tuple of suffixes (not including the `.`) that
    will be appended to the `basepath` and (optionally) the
    `shortpath` to generate suffixed (content-type specific) paths for
    the resource. Defaults to `('json', 'jsonld', 'ttl', 'csv')` if
    the resource supports `GET`, otherwise defaults to an empty tuple.

    If `register_basepath` is `True`, then the `basepath` (sans
    suffixes) will be added. Defaults to `True`.

    If `as_html` is `True`, then paths for the suffixes `json`,
    `jsonld`, and `ttl` will have an additional `htmlized` path
    added. Defaults to `False`.

    """

    def make_ok_response(_, data, headers=None, filename=None):
        return representations.make_ok_response(
            data,
            (suffixes + ("html",)) if as_html else suffixes,
            as_html,
            headers,
            filename,
        )

    def decorator(view_class: Type[Resource]):
        view = view_class.as_view(endpoint)
        methods = list(filter(lambda m: m in HTTP_METHODS, dir(view_class)))
        basepaths = [(endpoint, basepath)]

        def add_url_rule(path, endpoint):
            app.add_url_rule(path, endpoint=endpoint, view_func=view, methods=methods)

        if register_basepath and altpath is None:
            add_url_rule(basepath, endpoint)

        if shortpath is not None:
            short_endpoint = f"{endpoint}-short"
            basepaths.append((short_endpoint, shortpath))
            add_url_rule(shortpath, short_endpoint)

        if altpath is not None:
            add_url_rule(altpath, endpoint)

        if "get" in methods:
            for suffix in suffixes:
                for _endpoint, path in basepaths:
                    if path.endswith("/"):
                        path = path[:-1]

                    add_url_rule(f"{path}.{suffix}", f"{_endpoint}-{suffix}")

                    if as_html and not suffix == "csv":
                        add_url_rule(
                            f"{path}.{suffix}.html", f"{_endpoint}-{suffix}-html"
                        )

        setattr(view_class, "make_ok_response", make_ok_response)  # noqa: B010

        return view_class

    return decorator


def describe_endpoint(endpoint, description):
    return {
        "description": description,
        "url": (
            url_for(endpoint, _external=True)
            if not endpoint == "client"
            else app.config["CLIENT_URL"]
        ),
    }


INDEX = {
    "client": "PeriodO client (browse and edit periods)",
    "dataset": "PeriodO dataset",
    "description": "description of the PeriodO dataset",
    "patches": "patches submitted to the PeriodO dataset",
    "history": "history of changes to the PeriodO dataset",
    "bags": "user-defined subsets of the PeriodO dataset",
    "identifier-map": "a map of skolem IRIs that have been replaced with persistent IRIs",
    "context": "PeriodO JSON-LD context",
    "vocabulary": "PeriodO RDF vocabulary",
    "client-packages": "PeriodO client installation packages",
}


@register_resource(
    "index", "/index", altpath="/", suffixes=("json", "ttl"), as_html=True
)
class Index(Resource):
    def get(self):
        return self.make_ok_response(
            {
                endpoint: describe_endpoint(endpoint, description)
                for (endpoint, description) in INDEX.items()
            }
        )


VERSIONED_RESOURCE_ARGS = {"version": fields.Integer()}


@register_resource(
    "context", "/context", shortpath="/c", suffixes=("json",), as_html=True
)
class Context(Resource):
    def get(self):
        args = parser.parse(VERSIONED_RESOURCE_ARGS, request, location="query")
        version = args.get("version")

        try:
            dataset = get_dataset(version)
        except ResourceError as e:
            return e.response()

        context_etag = "periodo-context-version-{}".format(dataset["id"])
        if request.if_none_match.contains_weak(context_etag):
            return "", 304

        headers = {}
        headers["Last-Modified"] = format_date_time(dataset["created_at"])

        context = json.loads(dataset["data"]).get("@context")
        if context is None:
            return "", 404

        response = self.make_ok_response({"@context": context}, headers)
        response.set_etag(context_etag, weak=True)

        if version is None:
            return cache.no_time(response)
        else:
            return cache.long_time(response)


@register_resource("dataset", "/dataset/", shortpath="/d/")
class Dataset(Resource):
    def get(self):
        args = parser.parse(VERSIONED_RESOURCE_ARGS, request, location="query")
        version = args.get("version")
        filename = "periodo-dataset{}".format(
            "" if version is None else "-v{}".format(version)
        )

        try:
            dataset = get_dataset(version)
        except ResourceError as e:
            return e.response()

        dataset_etag = "periodo-dataset-version-{}".format(dataset["id"])
        if request.if_none_match.contains_weak(dataset_etag):
            return "", 304

        headers = {}
        headers["Last-Modified"] = format_date_time(dataset["created_at"])

        data = json.loads(dataset["data"])
        if version is not None and "@context" in data:
            data["@context"]["__version"] = version
        if "inline-context" in request.args:
            data["@context"]["__inline"] = True

        response = self.make_ok_response(
            attach_to_dataset(data), headers, filename=filename
        )
        response.set_etag(dataset_etag, weak=True)

        if version is None:
            return cache.short_time(response, server_only=True)
        else:
            return cache.long_time(response)

    @auth.submit_patch_permission.require()
    def patch(self):
        try:
            patch_request_id = patching.create_request(
                JsonPatch(parse_json(request)), g.identity.id
            )
            return "", 202, {"Location": url_for("patchrequest", id=patch_request_id)}
        except ResourceError as e:
            return e.response()
        except patching.InvalidPatchError as e:
            return {"status": 400, "message": str(e)}, 400


@register_resource(
    "history", "/history", shortpath="/h", suffixes=("nt",), register_basepath=False
)
class History(Resource):
    def get(self):
        response = self.make_ok_response(
            provenance.history(include_entity_details=("full" in request.args)),
            filename="periodo-history",
        )
        return cache.medium_time(response, server_only=True)


@register_resource(
    "authority",
    "/<string(length={}):authority_id>".format(
        identifier.AUTHORITY_SEQUENCE_LENGTH + 1
    ),
    register_basepath=False,
    as_html=True,
)
class Authority(Resource):
    def get(self, authority_id):
        version = request.args.get("version")
        new_location = redirect_to_last_update(authority_id, version)
        if new_location is not None:
            return new_location
        try:
            authority = attach_to_dataset(database.get_authority(authority_id, version))
            filename = "periodo-authority-{}{}".format(
                authority_id, "" if version is None else "-v{}".format(version)
            )
            return self.make_ok_response(authority, filename=filename)
        except database.MissingKeyError as e:
            abort_gone_or_not_found(e.key)


@register_resource(
    "period",
    "/<string(length={}):period_id>".format(
        identifier.AUTHORITY_SEQUENCE_LENGTH + 1 + identifier.PERIOD_SEQUENCE_LENGTH + 1
    ),
    register_basepath=False,
    as_html=True,
)
class Period(Resource):
    def get(self, period_id):
        version = request.args.get("version")
        new_location = redirect_to_last_update(period_id, version)
        if new_location is not None:
            return new_location
        try:
            period = attach_to_dataset(database.get_period(period_id, version))
            filename = "periodo-period-{}{}".format(
                period_id, "" if version is None else "-v{}".format(version)
            )
            return self.make_ok_response(period, filename=filename)
        except database.MissingKeyError as e:
            abort_gone_or_not_found(e.key)


PATCH_QUERY = """
SELECT patch_request.*, comment.message AS first_comment
FROM patch_request
LEFT JOIN (
  SELECT patch_request_id, message
  FROM patch_request_comment
  WHERE id IN (
    SELECT MIN(id)
    FROM patch_request_comment
    GROUP BY patch_request_id
  )
)
AS comment
ON comment.patch_request_id = patch_request.id
"""


class PatchRequestSchema(Schema):
    created_by = fields.String()
    created_at = W3CDTF()
    updated_by = fields.String()
    updated_at = W3CDTF()
    created_from = fields.String()
    applied_to = fields.String()
    identifier_map = fields.Raw()
    open = fields.Boolean()
    merged = fields.Boolean()
    first_comment = fields.String()
    url = fields.Function(
        lambda patch_request: url_for(
            "patchrequest", id=patch_request["id"], _external=True
        )
    )
    text = fields.Function(
        lambda patch_request: url_for("patch", id=patch_request["id"], _external=True)
    )

    class Meta:
        ordered = True


patchRequestListSchema = PatchRequestSchema(many=True)


@register_resource("patches", "/patches/", suffixes=("json",))
class PatchRequestList(Resource):
    PATCH_REQUEST_LIST_ARGS = {
        "sort": fields.String(
            validate=validate.OneOf(["created_at", "updated_at"]),
            load_default="updated_at",
        ),
        "order": fields.String(
            validate=validate.OneOf(["asc", "desc"]), load_default="desc"
        ),
        "open": fields.Boolean(),
        "merged": fields.Boolean(),
        "limit": fields.Integer(load_default=25),
        "from": fields.Integer(load_default=0),
    }

    def get(self):
        args = parser.parse(self.PATCH_REQUEST_LIST_ARGS, request, location="query")
        query = PATCH_QUERY
        params = ()

        where = []
        if "open" in args:
            where.append("open = ?")
            params += (args.get("open"),)
        if "merged" in args:
            where.append("merged = ?")
            params += (args.get("merged"),)
        if where:
            query += f" WHERE {' AND '.join(where)}"

        query += f" ORDER by {args['sort']} {args['order']}, patch_request.id DESC"

        limit = args["limit"]
        if limit < 0:
            limit = 25
        if limit > 250:
            limit = 250

        offset = args["from"]
        if offset < 0:
            offset = 0
        query += f" LIMIT {limit + 1} OFFSET {offset}"

        rows = database.query_db_for_all(query, params)
        data = [process_patch_row(row) for row in rows][:limit]
        count = database.query_db_for_one(
            "SELECT COUNT(*) AS count FROM patch_request"
        )["count"]

        link_headers = []

        if offset > 0:
            prev_url = url_for("patches", _external=True)

            prev_params = request.args.to_dict().copy()
            prev_params["from"] = offset - limit
            if prev_params["from"] <= 0:
                prev_params.pop("from")

            prev_params = urlencode(prev_params)
            if prev_params:
                prev_url += "?" + prev_params

            link_headers.append('<{}>; rel="prev"'.format(prev_url))

        # We fetched 1 more than the limit. If there are limit+1 rows in the
        # retrieved query, then there are more rows to be fetched
        if len(rows) > limit:
            next_url = url_for("patches", _external=True)
            next_params = request.args.to_dict().copy()

            next_params["from"] = offset + limit
            link_headers.append(
                '<{}?{}>; rel="next"'.format(next_url, urlencode(next_params))
            )

        headers = {}

        if link_headers:
            headers["Link"] = ", ".join(link_headers)

        headers["X-Total-Count"] = count

        return self.make_ok_response(
            patchRequestListSchema.dump(data), headers, filename="periodo-patches"
        )


class CommentSchema(Schema):
    author = fields.String()
    posted_at = W3CDTF()
    message = fields.String()


class PatchSchema(PatchRequestSchema):
    mergeable = fields.Boolean()
    comments = fields.List(fields.Nested(CommentSchema))


patchSchema = PatchSchema()


@register_resource("patchrequest", "/patches/<int:id>/", suffixes=("json",))
class PatchRequest(Resource):
    def get(self, id):
        row = database.query_db_for_one(
            PATCH_QUERY + " where patch_request.id = ?", (id,)
        )
        if not row:
            abort(404)
        data = process_patch_row(row)
        data["mergeable"] = patching.is_mergeable(data["original_patch"])
        data["comments"] = [dict(c) for c in database.get_patch_request_comments(id)]
        headers = {}
        try:
            if auth.accept_patch_permission.can():
                headers["Link"] = '<{}>;rel="merge"'.format(
                    url_for("patch-merge", id=id)
                )
        except auth.AuthenticationFailed:
            pass

        return patchSchema.dump(data), 200, headers


@register_resource(
    "patch",
    "/patches/<int:id>/patch",
    altpath="/patches/<int:id>/patch.jsonpatch",
    suffixes=("json",),
)
class Patch(Resource):
    def get(self, id):
        row = database.query_db_for_one(
            PATCH_QUERY + " where patch_request.id = ?", (id,)
        )
        if not row:
            abort(404)
        if row["merged"]:
            patch = row["applied_patch"]
        else:
            patch = row["original_patch"]
        return patch, 200, {"Content-Type": "application/json"}

    def put(self, id):
        permission = auth.UpdatePatchPermission(id)
        if not permission.can():
            raise auth.PermissionDenied(permission)
        try:
            patch = JsonPatch(parse_json(request))
            patching.update_request(id, patch, g.identity.id)
        except ResourceError as e:
            return e.response()
        except patching.InvalidPatchError as e:
            if str(e) != "Could not apply JSON patch to dataset.":
                return {"status": 400, "message": str(e)}, 400

        return "", 200


@register_resource("patch-merge", "/patches/<int:id>/merge")
class PatchMerge(Resource):
    @auth.accept_patch_permission.require()
    def post(self, id):
        try:
            patching.merge(id, g.identity.id)
            cache.purge_history()
            cache.purge_dataset()
            cache.purge_graphs()
            return "", 204
        except patching.UnmergeablePatchError as e:
            return {"message": str(e)}, 400
        except patching.MergeError as e:
            return {"message": str(e)}, 404


@register_resource("patch-reject", "/patches/<int:id>/reject")
class PatchReject(Resource):
    @auth.accept_patch_permission.require()
    def post(self, id):
        try:
            patching.reject(id, g.identity.id)
            return "", 204
        except patching.MergeError as e:
            return {"message": str(e)}, 404


@register_resource("patch-messages", "/patches/<int:id>/messages")
class PatchMessages(Resource):
    @auth.submit_patch_permission.require()
    def post(self, id):
        data = request.data or ""
        if isinstance(data, bytes):
            data = data.decode()

        try:
            data = json.loads(data)
            message = data["message"]
        except KeyError:
            return {"message": "No message present in request data."}, 400

        try:
            patching.add_comment(id, g.identity.id, message)
            return "", 200, {"Location": url_for("patchrequest", id=id)}
        except patching.MergeError as e:
            return {"message": str(e)}, 404


@register_resource(
    "identifier-map",
    "/identifier-map/",
    suffixes=("json",),
)
class IdentifierMap(Resource):
    def get(self):
        identifier_map, last_edited = database.get_identifier_map()

        headers = {}
        if last_edited is not None:
            headers["Last-Modified"] = format_date_time(last_edited)

        response = self.make_ok_response(
            {"identifier_map": identifier_map},
            headers,
            filename="periodo-identifier-map",
        )

        return cache.long_time(response, server_only=True)


@register_resource("bags", "/bags/", suffixes=("json",), as_html=True)
class Bags(Resource):
    def get(self):
        return self.make_ok_response(
            [
                url_for("bag", uuid=uuid, _external=True)
                for uuid in database.get_bag_uuids()
            ]
        )


@register_resource("bag", "/bags/<uuid:uuid>", suffixes=("json",), as_html=True)
class Bag(Resource):
    @auth.update_bag_permission.require()
    def put(self, uuid):

        try:
            data = parse_json(request)
        except ResourceError as e:
            return e.response()

        title = str(data.get("title", ""))
        if len(title) == 0:
            return {"message": "A bag must have a title"}, 400

        items = data.get("items", [])
        if len(items) < 2:
            return {"message": "A bag must have at least two items"}, 400

        try:
            _, ctx = database.get_periods_and_context(items, raiseErrors=True)
        except database.MissingKeyError as e:
            return {"message": "No resource with key: " + e.key}, 400

        base = ctx["@base"]
        bag_ctx = data.get("@context", {})
        context_url = utils.absolute_url(ctx["@base"], "context-short")
        if type(bag_ctx) is list:
            contexts = bag_ctx
            if context_url not in contexts:
                contexts.insert(0, context_url)
            if type(contexts[-1]) is dict:
                contexts[-1]["@base"] = base
            else:
                contexts.append({"@base": base})
        else:
            contexts = [context_url, {**bag_ctx, "@base": base}]

        data["@context"] = contexts

        bag = database.get_bag(uuid)
        if bag and g.identity.id not in json.loads(bag["owners"]):
            return "", 403

        version = database.create_or_update_bag(uuid, g.identity.id, data)
        return "", 201, {"Location": url_for("bag", uuid=uuid, version=version)}

    def get(self, uuid):
        args = parser.parse(VERSIONED_RESOURCE_ARGS, request, location="query")
        version = args.get("version")
        bag = database.get_bag(uuid, version=version)

        if not bag:
            abort(404)

        bag_etag = "bag-{}-version-{}".format(uuid, bag["version"])
        if request.if_none_match.contains_weak(bag_etag):
            return "", 304

        headers = {}
        headers["Last-Modified"] = format_date_time(bag["created_at"])

        data = json.loads(bag["data"])
        defs, _ = database.get_periods_and_context(data["items"])

        data["@id"] = identifier.prefix("bags/%s" % uuid)
        data["creator"] = bag["created_by"]
        data["items"] = defs

        response = self.make_ok_response(data, headers)
        response.set_etag(bag_etag, weak=True)

        if version is None:
            return cache.no_time(response)
        else:
            return cache.long_time(response)


def external_graph_url(graph, version):
    if version is None:
        return url_for("graph", id=graph["id"], _external=True)
    return url_for("graph", id=graph["id"], version=version, _external=True)


def graph_container(url, graphs, version=None):
    return {
        "@context": {
            "@version": 1.1,
            "graphs": {"@id": url, "@container": ["@graph", "@id"]},
        },
        "graphs": {
            external_graph_url(graph, version): json.loads(graph["data"])
            for graph in graphs
        },
    }


def get_graphs(prefix=None):
    if prefix and prefix.endswith("/"):
        prefix = prefix[:-1]
    url = url_for("graphs", _external=True) + ((prefix + "/") if prefix else "")
    return graph_container(url, database.get_graphs(prefix))


@register_resource("graphs", "/graphs/", suffixes=("json",))
class Graphs(Resource):
    def get(self):
        data = get_graphs()
        dataset = database.get_dataset()
        if dataset:
            dataset_url = url_for("dataset-short", _external=True)
            data["graphs"][dataset_url] = json.loads(dataset["data"])
        return cache.medium_time(self.make_ok_response(data, filename="periodo-graphs"))


@register_resource("graph", "/graphs/<path:id>", suffixes=("json",))
class Graph(Resource):
    @auth.update_graph_permission.require()
    def put(self, id):
        if id.endswith("/"):
            return {"message": "graph uri path cannot end in /"}, 400
        try:
            version = database.create_or_update_graph(id, parse_json(request))
            if version > 0:
                cache.purge_graph(id)
            return "", 201, {"Location": url_for("graph", id=id, version=version)}
        except ResourceError as e:
            return e.response()

    def get(self, id):
        data = get_graphs(prefix=id)
        filename = "periodo-graph-{}".format(id.replace("/", "-"))

        if len(data["graphs"]) > 0:
            return cache.medium_time(self.make_ok_response(data, filename=filename))

        args = parser.parse(VERSIONED_RESOURCE_ARGS, request, location="query")
        version = args.get("version")
        graph = database.get_graph(id, version=version)
        filename += "" if version is None else "-v{}".format(version)

        if not graph:
            abort(404)

        graph_etag = "graph-{}-version-{}".format(id, graph["version"])
        if request.if_none_match.contains_weak(graph_etag):
            return "", 304

        headers = {}
        headers["Last-Modified"] = format_date_time(graph["created_at"])

        data = graph_container(external_graph_url(graph, version), [graph], version)
        response = self.make_ok_response(data, headers, filename=filename)
        response.set_etag(graph_etag, weak=True)

        if version is None:
            return cache.medium_time(response)
        else:
            return cache.long_time(response)

    @auth.update_graph_permission.require()
    def delete(self, id):
        if database.delete_graph(id):
            cache.purge_graph(id)
            return "", 204
        else:
            abort(404)


@register_resource("identity", "/identity", suffixes=("json",))
class Identity(Resource):
    # submit_patch is the minimal permission
    @auth.submit_patch_permission.require()
    def get(self):
        if g.identity.id is None:  # shouldn't be possible but just in case
            return {}, 200
        user = database.query_db_for_one(
            "SELECT name FROM user WHERE id = ?", (g.identity.id,)
        )
        return {
            "id": g.identity.id,
            "name": user["name"],
            "permissions": auth.describe(g.identity.provides),
        }, 200
