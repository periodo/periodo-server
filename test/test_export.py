import gzip
import httpx
import os
import pytest
import sqlite3
from periodo import app, dump


@pytest.fixture
def background_builds(monkeypatch):
    builds = []
    monkeypatch.setattr(dump, "build_in_background", lambda *args: builds.append(args))
    return builds


def build():
    with app.app_context():
        return dump.build(app.config["DATABASE"], dump.path())


def load(sql):
    db = sqlite3.connect(":memory:")
    db.executescript(sql)
    return db


def count_rows(db, table):
    return db.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]


def test_export_not_built_yet(client, background_builds):
    res = client.get("/export.sql")
    assert res.status_code == httpx.codes.SERVICE_UNAVAILABLE
    assert res.headers["Retry-After"] == "300"
    assert len(background_builds) == 1


def test_export(client, active_user, submit_and_merge_patch, background_builds):
    submit_and_merge_patch("test-patch-adds-items.json")
    assert build()

    res = client.get("/export.sql")
    assert res.status_code == httpx.codes.OK
    assert res.headers["Content-Type"] == "text/plain; charset=utf-8"
    assert res.headers["Content-Encoding"] == "gzip"
    assert res.headers["Content-Length"] == str(os.path.getsize(dump.path()))
    assert "Accept-Encoding" in res.headers["Vary"]
    assert res.headers["Content-Disposition"].startswith(
        'attachment; filename="periodo-export-'
    )
    assert background_builds == []

    exported = load(res.text)
    original = sqlite3.connect(app.config["DATABASE"])
    for table in ("dataset", "patch_request", "sqlite_sequence"):
        assert count_rows(exported, table) > 0
        assert exported.execute(f"SELECT * FROM {table}").fetchall() == (
            original.execute(f"SELECT * FROM {table}").fetchall()
        )
    assert count_rows(original, "user") > 0
    assert count_rows(exported, "user") == 0
    assert "this-token-has-normal-permissions" not in res.text
    assert exported.execute(
        "SELECT name FROM sqlite_master WHERE type = 'trigger' ORDER BY name"
    ).fetchall() == [("update_patch",), ("update_user_credentials",)]


def test_export_uncompressed(client, background_builds):
    assert build()
    res = client.get("/export.sql", headers={"Accept-Encoding": "identity"})
    assert res.status_code == httpx.codes.OK
    assert "Content-Encoding" not in res.headers
    with gzip.open(dump.path(), "rt") as f:
        assert res.text == f.read()
    assert res.text.startswith("PRAGMA foreign_keys=OFF;\nBEGIN TRANSACTION;\n")
    assert res.text.endswith("COMMIT;\n")


def test_stale_export_is_served_and_rebuilt(client, background_builds):
    assert build()
    assert not build()  # already fresh

    # Make the export older than the latest write to the database.
    mtime_ns = os.stat(app.config["DATABASE"]).st_mtime_ns - 1_000_000_000
    os.utime(dump.path(), ns=(mtime_ns, mtime_ns))

    res = client.get("/export.sql")
    assert res.status_code == httpx.codes.OK
    assert len(background_builds) == 1
    assert build()
