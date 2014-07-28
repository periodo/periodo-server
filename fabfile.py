import json
import sqlite3

from fabric.api import *

@task
def setup():
    install_deps()
    init_db()

@task
def install_deps():
    local('virtualenv .')
    local('./bin/pip install -r requirements.txt')

@task
def init_db():
    local('bin/python -c "from periodo import init_db; init_db()"')

@task
def load_data(datafile):
    db = sqlite3.connect('./db.sqlite')

    with open(datafile) as f, db:
        data = json.load(f)
        db.execute(u'insert into dataset (data) values (?)', (json.dumps(data),))

    print('Data loaded from {}.'.format(datafile))
