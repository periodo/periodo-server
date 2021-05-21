import json
from jsonpatch import JsonPatch
from periodo import app, auth, database, patching


def init_db():
    with app.app_context():
        with app.open_resource("schema.sql", mode="r") as schema_file:
            with database.open_cursor(write=True) as cursor:
                cursor.executescript(schema_file.read())


def load_data(datafile):
    with app.app_context():
        with open(datafile) as f:
            data = json.load(f)
        user_id = "initial-data-loader"
        patch = JsonPatch.from_diff({}, data)
        patch_request_id = patching.create_request(patch, user_id)
        patching.merge(patch_request_id, user_id)


def set_permissions(orcid, permissions=None):
    if permissions is None:
        permissions = []

    with app.app_context():
        with database.open_cursor(write=True) as cursor:
            cursor.execute("select id from user where id=?", [orcid])

            user = cursor.fetchone()

            if user is None:
                raise ValueError('No user with orcid "{}" in database.'.format(orcid))

            needs = set()

            for permission_name in permissions:
                permission_attr = "{}_permission".format(permission_name)
                permission = getattr(auth, permission_attr, None)

                if permission is None:
                    raise ValueError("No such permission: {}".format(permission_name))

                for need in permission.needs:
                    needs.add(tuple(need))

            cursor.execute(
                "UPDATE user SET permissions = ? WHERE id = ?",
                [json.dumps(list(needs)), orcid],
            )
