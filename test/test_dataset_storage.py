import httpx
import sqlite3
from periodo import app, commands, database


def raw_rows():
    db = sqlite3.connect(app.config["DATABASE"])
    return db.execute(
        "SELECT id, typeof(data), data FROM dataset ORDER BY id"
    ).fetchall()


def all_versions():
    with app.app_context():
        return [database.get_dataset(id) for id, _, _ in raw_rows()]


def test_merged_versions_are_compressed(client, submit_and_merge_patch):
    res = submit_and_merge_patch("test-patch-adds-items.json")
    assert res.status_code == httpx.codes.NO_CONTENT
    for id, data_type, _ in raw_rows():
        # version 0 is the empty dataset inserted by schema.sql
        assert data_type == ("text" if id == 0 else "blob")
    res = client.get("/d.json")
    assert res.status_code == httpx.codes.OK
    assert "p0trgkv" in res.json()["authorities"]


def test_compress_datasets(client, submit_and_merge_patch):
    submit_and_merge_patch("test-patch-adds-items.json")
    submit_and_merge_patch("test-patch-add-period.json")

    # Store the versions uncompressed, as they were before compression.
    db = sqlite3.connect(app.config["DATABASE"])
    for id, _, data in raw_rows():
        db.execute(
            "UPDATE dataset SET data = ? WHERE id = ?",
            (database.decompress_dataset(data), id),
        )
    db.commit()
    assert {data_type for _, data_type, _ in raw_rows()} == {"text"}

    before = all_versions()
    commands.compress_datasets(batch_size=2)
    commands.vacuum()

    assert {data_type for _, data_type, _ in raw_rows()} == {"blob"}
    assert all_versions() == before
    for version in range(len(before)):
        res = client.get("/d.json", params={"version": version})
        assert res.status_code == httpx.codes.OK
