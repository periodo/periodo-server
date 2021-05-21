import itertools
import json
import sqlite3
from contextlib import contextmanager
from periodo import app, identifier, auth
from flask import g, url_for
from uuid import UUID


class MissingKeyError(Exception):  # noqa: B903
    def __init__(self, key):
        self.key = key


def _get_db_connection():
    db = getattr(g, "_database", None)
    if db is None:
        db = g._database = sqlite3.connect(app.config["DATABASE"])
        db.row_factory = sqlite3.Row
    return db


@contextmanager
def open_cursor(write=False, trace=False):
    db = _get_db_connection()
    if trace:
        db.set_trace_callback(app.logger.debug)
    c = db.cursor()
    try:
        yield c
    except Exception:
        if write:
            db.rollback()
        raise
    else:
        if write:
            db.commit()
    finally:
        c.close()
        if trace:
            db.set_trace_callback(None)


def query_db_for_all(query, args=()) -> list[sqlite3.Row]:
    with open_cursor() as c:
        c.execute(query, args)
        return c.fetchall()


def query_db_for_one(query, args=()) -> sqlite3.Row:
    with open_cursor() as c:
        c.execute(query, args)
        return c.fetchone()


def get_user(user_id):
    row = query_db_for_one(
        "SELECT id, name, b64token FROM user WHERE id = ?", (user_id,)
    )
    return auth.User(row["id"], row["name"], row["b64token"])


def get_dataset(version=None) -> sqlite3.Row:
    if version is None:
        return query_db_for_one("SELECT * FROM dataset ORDER BY id DESC LIMIT 1")
    else:
        return query_db_for_one(
            "SELECT * FROM dataset WHERE dataset.id = ?", (version,)
        )


def get_context(version=None):
    return json.loads(get_dataset(version)["data"]).get("@context")


def extract_authority(authority_key, o, raiseErrors=False):
    def maybeRaiseMissingKeyError():
        if raiseErrors:
            raise MissingKeyError(authority_key)

    if "authorities" not in o:
        maybeRaiseMissingKeyError()
        return None

    if authority_key not in o["authorities"]:
        maybeRaiseMissingKeyError()
        return None

    return o["authorities"][authority_key]


def extract_period(period_key, o, raiseErrors=False):
    def maybeRaiseMissingKeyError():
        if raiseErrors:
            raise MissingKeyError(period_key)

    authority_key = period_key[:7]
    authority = extract_authority(authority_key, o, raiseErrors)

    if period_key not in authority["periods"]:
        maybeRaiseMissingKeyError()
        return None

    period = authority["periods"][period_key]
    period["authority"] = authority_key

    return period


def get_item(extract_item, id, version=None):
    dataset = get_dataset(version=version)
    o = json.loads(dataset["data"])
    item = extract_item(identifier.prefix(id), o, raiseErrors=True)
    item["@context"] = o["@context"]
    if version is not None:
        item["@context"]["__version"] = version

    return item


def get_authority(id, version=None):
    return get_item(extract_authority, id, version)


def get_period(id, version=None):
    return get_item(extract_period, id, version)


def get_periods_and_context(ids, version=None, raiseErrors=False):
    dataset = get_dataset(version=version)
    o = json.loads(dataset["data"])
    periods = {id: extract_period(id, o, raiseErrors) for id in ids}

    return periods, o["@context"]


def get_patch_request_comments(patch_request_id):
    return query_db_for_all(
        """
SELECT id, author, message, posted_at
FROM patch_request_comment
WHERE patch_request_id=?
ORDER BY posted_at ASC""",
        (patch_request_id,),
    )


def get_merged_patches():
    return query_db_for_all(
        """
SELECT
  patch_request.id AS id,
  created_at,
  created_by,
  updated_by,
  merged_at,
  merged_by,
  applied_to,
  resulted_in,
  created_entities,
  updated_entities,
  removed_entities,
  COUNT(patch_request_comment.id) AS comment_count
FROM patch_request
LEFT OUTER JOIN patch_request_comment
ON patch_request_comment.patch_request_id = patch_request.id
WHERE merged = 1
GROUP BY patch_request.id
ORDER BY id ASC
"""
    )


def get_identifier_map():
    map_rows = query_db_for_all(
        """
        SELECT identifier_map, merged_at FROM patch_request
        WHERE merged = TRUE AND
        LENGTH(identifier_map) > 2
        ORDER BY merged_at
        """
    )

    identifier_map = {}
    last_edited = None

    for row in map_rows:
        identifier_map.update(json.loads(row["identifier_map"]))
        last_edited = row["merged_at"]

    return identifier_map, last_edited


def get_bag_uuids():
    return [UUID(row["uuid"]) for row in query_db_for_all("SELECT uuid FROM bag")]


def get_bag(uuid, version=None):
    if version is None:
        return query_db_for_one(
            "SELECT * FROM bag WHERE uuid = ? ORDER BY version DESC LIMIT 1",
            (uuid.hex,),
        )
    else:
        return query_db_for_one(
            "SELECT * FROM bag WHERE uuid = ? AND version = ?", (uuid.hex, version)
        )


def get_graphs(prefix=None):
    if prefix is None:
        return query_db_for_all(
            """
SELECT graph.id AS id, graph.data AS data
FROM (
   SELECT id, MAX(version) AS maxversion
   FROM graph
   WHERE deleted = 0
   GROUP BY id
) AS g
INNER JOIN graph
ON g.id = graph.id
AND g.maxversion = graph.version
"""
        )
    else:
        return query_db_for_all(
            """
SELECT graph.id AS id, graph.data AS data
FROM (
   SELECT id, MAX(version) AS maxversion
   FROM graph
   WHERE deleted = 0
   AND id LIKE ?
   GROUP BY id
) AS g
INNER JOIN graph
ON g.id = graph.id
AND g.maxversion = graph.version
""",
            (prefix + "/%",),
        )


def get_graph(id, version=None):
    if version is None:
        return query_db_for_one(
            """
        SELECT * FROM graph
        WHERE id = ? AND deleted = 0
        ORDER BY version DESC LIMIT 1
        """,
            (id,),
        )
    else:
        return query_db_for_one(
            """
        SELECT * FROM graph
        WHERE id = ? AND version = ?
        """,
            (id, version),
        )


def create_or_update_bag(uuid, creator_id, data):
    with open_cursor(write=True) as c:
        c.execute(
            """
        SELECT MAX(version) AS max_version
        FROM bag
        WHERE uuid = ?
        """,
            (uuid.hex,),
        )
        row = c.fetchone()
        version = 0 if row["max_version"] is None else row["max_version"] + 1
        if version > 0:
            data["wasRevisionOf"] = identifier.prefix(
                f"bags/{uuid}?version={row['max_version']}"
            )
        c.execute(
            """
        INSERT INTO bag (
        uuid,
        version,
        created_by,
        data,
        owners)
        VALUES (?, ?, ?, ?, ?)
        """,
            (
                uuid.hex,
                version,
                creator_id,
                json.dumps(data, ensure_ascii=False),
                json.dumps([creator_id]),
            ),
        )
        return version


def create_or_update_graph(id, data):
    with open_cursor(write=True) as c:
        c.execute(
            """
        SELECT MAX(version) AS max_version
        FROM graph
        WHERE id = ?
        """,
            (id,),
        )
        row = c.fetchone()
        version = 0 if row["max_version"] is None else row["max_version"] + 1
        if version > 0:
            data["wasRevisionOf"] = url_for(
                "graph", id=id, version=row["max_version"], _external=True
            )
        c.execute(
            """
        INSERT INTO graph (
        id,
        version,
        data)
        VALUES (?, ?, ?)
        """,
            (id, version, json.dumps(data, ensure_ascii=False)),
        )
        return version


def delete_graph(id):
    with open_cursor(write=True) as c:
        c.execute("UPDATE graph SET deleted = 1 WHERE id = ?", (id,))
        return c.rowcount > 0


def find_version_of_last_update(entity_id, version):
    for row in query_db_for_all(
        """
    SELECT created_entities, updated_entities, resulted_in
    FROM patch_request
    WHERE merged = 1
    AND resulted_in <= ?
    ORDER BY id DESC
    """,
        (version,),
    ):
        if entity_id in json.loads(row["created_entities"]):
            return row["resulted_in"]
        if entity_id in json.loads(row["updated_entities"]):
            return row["resulted_in"]
    return None


def get_removed_entity_keys():
    return set(
        itertools.chain(
            *[
                json.loads(row["removed_entities"])
                for row in query_db_for_all(
                    """
        SELECT removed_entities FROM patch_request WHERE merged = 1
        """
                )
            ]
        )
    )


def dump():
    return _get_db_connection().iterdump()


@app.teardown_appcontext
def close(_):
    db = getattr(g, "_database", None)
    if db is not None:
        db.close()
