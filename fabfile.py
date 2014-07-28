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
