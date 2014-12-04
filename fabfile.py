import json
import sqlite3

from fabric.api import *

@task
def setup():
    install_deps()
    init_db()

@task
def install_deps():
    local('virtualenv . -p python3')
    local('./bin/pip3 install -r requirements.txt')

@task
def init_db():
    local('bin/python3 -c "from periodo import init_db; init_db()"')

@task
def load_data(datafile):
    local('./bin/python3 -c "from periodo import load_data; load_data(\'{}\')"'.format(datafile))
    print('Data loaded from {}.'.format(datafile))
