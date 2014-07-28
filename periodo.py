import sqlite3

from flask import Flask, g

__all__ = ['init_db']

DATABASE = './db.sqlite'


#########
# Setup #
#########

app = Flask(__name__)
app.config.update(
    DEBUG=True
)


######################
#  Database handling #
######################

def init_db():
    with app.app_context():
        db = get_db()
        with app.open_resource('schema.sql', mode='r') as schema_file:
            db.cursor().executescript(schema_file.read())
        db.commit()

def get_db():
    db = getattr(g, '_database', None)
    if db is None:
        db = g._database = sqlite3.connect(DATABASE)
        db.row_factory = sqlite3.Row
    return db

def query_db(query, args=(), one=False):
    curs = get_db().execute(query, args)
    rows = curs.fetchall()
    curs.close()
    return (rows[0] if rows else None) if one else rows

@app.teardown_appcontext
def close_connection(exception):
    db = getattr(g, '_database', None)
    if db is not None:
        db.close()


############################
# End of meaningful things #
############################

if __name__ == '__main__':
    app.run()
