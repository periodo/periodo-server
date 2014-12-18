import json
import sqlite3
import urllib2

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

@task
def get_latest_client():
    url = 'https://api.github.com/repos/periodo/periodo-client/releases'
    page = urllib2.urlopen(url)
    releases = json.load(page)

    request = urllib2.Request(releases[0]['assets'][0]['url'],
                              headers={'Accept': 'application/octet-stream'})
    zip_resp = urllib2.urlopen(request)

    with open('client.zip', 'w') as tmp_zip:
        tmp_zip.write(zip_resp.read())

    local('mkdir -p static/html')
    local('unzip client.zip -d static/html')
    local('rm client.zip')
