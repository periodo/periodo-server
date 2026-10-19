import fcntl
import gzip
import os
import sqlite3
import threading
import time
from periodo import app

# Rows of these tables hold credentials, so only their schema is exported.
EXCLUDED_TABLES = {"user"}

# The content of rows of this table never changes once inserted (only
# commands.compress_datasets() changes how it is stored), so they can be read
# after the snapshot of the other tables, without holding a read lock while
# hundreds of large dataset versions are compressed.
APPEND_ONLY_TABLE = "dataset"

# Dataset versions are several MB each, so read only a few at a time.
BATCH_SIZE = 10


def path():
    return os.path.splitext(app.config["DATABASE"])[0] + "-export.sql.gz"


def _db_mtime_ns(db_path):
    return max(
        os.stat(p).st_mtime_ns for p in (db_path, db_path + "-wal") if os.path.exists(p)
    )


def is_fresh(db_path, export_path):
    # A built export has its mtime set to the database's mtime at the start of
    # the build, so any later write to the database makes the export stale.
    try:
        return os.stat(export_path).st_mtime_ns >= _db_mtime_ns(db_path)
    except FileNotFoundError:
        return False


def _quote(name):
    return '"{}"'.format(name.replace('"', '""'))


def _insert_statement(conn, table):
    "An SQL expression that evaluates to an INSERT statement for a row of table."
    columns = [row[1] for row in conn.execute(f"PRAGMA table_info({_quote(table)})")]
    values = " || ',' || ".join(f"quote({_quote(c)})" for c in columns)
    return f"'INSERT INTO {_quote(table)} VALUES(' || {values} || ')'"


def write(db_path, f):
    """Write an SQL dump of the database to f, in the same format as
    sqlite3.Connection.iterdump(), but without rows of EXCLUDED_TABLES."""
    conn = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True, isolation_level=None)
    try:
        f.write("PRAGMA foreign_keys=OFF;\n")
        f.write("BEGIN TRANSACTION;\n")
        conn.execute("BEGIN")
        tables = conn.execute(
            "SELECT name, sql FROM sqlite_master "
            "WHERE sql NOT NULL AND type = 'table' ORDER BY name"
        ).fetchall()
        for name, sql in tables:
            if name == "sqlite_sequence":
                f.write('DELETE FROM "sqlite_sequence";\n')
            elif name.startswith("sqlite_"):
                continue
            else:
                f.write(f"{sql};\n")
            if name in EXCLUDED_TABLES or name == APPEND_ONLY_TABLE:
                continue
            for (statement,) in conn.execute(
                f"SELECT {_insert_statement(conn, name)} FROM {_quote(name)}"
            ):
                f.write(f"{statement};\n")
        (max_dataset_id,) = conn.execute(
            f"SELECT MAX(id) FROM {_quote(APPEND_ONLY_TABLE)}"
        ).fetchone()
        others = conn.execute(
            "SELECT sql FROM sqlite_master "
            "WHERE sql NOT NULL AND type IN ('index', 'trigger', 'view')"
        ).fetchall()
        conn.execute("COMMIT")

        # Fetch each batch before writing it, so that no read lock is held
        # while writing.
        query = (
            f"SELECT id, {_insert_statement(conn, APPEND_ONLY_TABLE)} "
            f"FROM {_quote(APPEND_ONLY_TABLE)} "
            "WHERE id > ? AND id <= ? ORDER BY id LIMIT ?"
        )
        last_id = -1
        while rows := conn.execute(
            query, (last_id, max_dataset_id, BATCH_SIZE)
        ).fetchall():
            for _, statement in rows:
                f.write(f"{statement};\n")
            last_id = rows[-1][0]

        for (sql,) in others:
            f.write(f"{sql};\n")
        f.write("COMMIT;\n")
    finally:
        conn.close()


def build(db_path, export_path):
    """Build a gzipped export of the database, unless it is already fresh or
    another thread or process is building it. Returns True if it was built."""
    with open(export_path + ".lock", "w") as lock:
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            return False
        if is_fresh(db_path, export_path):
            return False
        started = time.monotonic()
        db_mtime_ns = _db_mtime_ns(db_path)
        tmp_path = export_path + ".tmp"
        with gzip.open(tmp_path, "wt", encoding="utf-8", compresslevel=6) as f:
            write(db_path, f)
        os.utime(tmp_path, ns=(db_mtime_ns, db_mtime_ns))
        os.replace(tmp_path, export_path)
        app.logger.info("built %s in %.1f s", export_path, time.monotonic() - started)
        return True


def _build_and_log_errors(db_path, export_path):
    try:
        build(db_path, export_path)
    except Exception:
        app.logger.exception("failed to build %s", export_path)


def build_in_background(db_path, export_path):
    thread = threading.Thread(
        target=_build_and_log_errors, args=(db_path, export_path), daemon=True
    )
    thread.start()
    return thread
