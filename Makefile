VENV_DIR := venv
PYTHON3 := $(VENV_DIR)/bin/python3
PYTEST := $(VENV_DIR)/bin/pytest
FLASK := $(VENV_DIR)/bin/flask
DB := ./db.sqlite
SERVER_VERSION := $(shell git describe | cut -c 2-)
SKIP_TRANSLATION ?= false

.PHONY: all
all: $(DB)

$(PYTHON3):
	python3 -m venv $(VENV_DIR)
	$(PYTHON3) -m pip install --upgrade pip
	$(PYTHON3) -m pip install wheel
	$(PYTHON3) -m pip install -r requirements.txt

.PHONY: $(DB)
$(DB): | $(PYTHON3)
	DATABASE=$(DB) $(PYTHON3) -c\
	 "from periodo.commands import init_db; init_db()";

.PHONY: load_data
load_data: | $(PYTHON3)
ifeq ($(DATA),)
	$(error No data file provided. Run `make load_data DATA=/path/to/data/file`)
endif
	DATABASE=$(DB) $(PYTHON3) -c\
	 "from periodo.commands import load_data; load_data('$(DATA)')"

export.sql.gz:
ifeq ($(IMPORT_URL),)
	$(error No import URL provided. Run e.g. `make import IMPORT_URL=https://data.staging.perio.do/export.sql`)
endif
	curl -X GET -H 'Accept-Encoding: gzip' "$(IMPORT_URL)" > $@

.PHONY: import
import: export.sql.gz
ifneq ($(wildcard $(DB)),)
	TS=`date -u +%FT%TZ` && mv $(DB) "$(DB)-$$TS.bak"
endif
	cat $< | gunzip | sqlite3 $(DB)

.PHONY: set_permissions
set_permissions: | $(PYTHON3)
ifeq ($(ORCID),)
	$(error No orcid provided. Run `make set_permissions ORCID=https://orcid.org/0000-1234 PERMISSIONS=perm1,perm2,perm3`)
endif
	DATABASE=$(DB) $(PYTHON3) -c\
	 "from periodo.commands import set_permissions; set_permissions('$(ORCID)','$(PERMISSIONS)'.split(','))"

.PHONY: clean
clean:
	rm -rf $(VENV_DIR)

.PHONY: test
test: | $(PYTHON3)
	TESTING=1 SKIP_TRANSLATION=$(SKIP_TRANSLATION) $(PYTEST) test -x

.PHONY: run
run: test
	set -a && \
	source .env.prod && \
	set +a && \
	$(FLASK) --app periodo run

.PHONY: stage publish

stage: APP_CONFIG = fly.stage.toml

publish: APP_CONFIG = fly.publish.toml

stage publish: clean test
	fly deploy \
	--config $(APP_CONFIG) \
	--env SERVER_VERSION=$(SERVER_VERSION)
