VENV_DIR := venv
PIP3 := $(VENV_DIR)/bin/pip3
PYTHON3 := $(VENV_DIR)/bin/python3
PYTEST := $(VENV_DIR)/bin/pytest
DB := ./db.sqlite

VOCAB_FILES := $(shell find vocab -name *.ttl)
SHAPE_FILES := $(shell find shapes -name *.ttl)

.PHONY: all
all: vocab.html $(DB)

$(PYTHON3):
	python3 -m venv $(VENV_DIR)
	$(PIP3) install --upgrade pip
	$(PIP3) install wheel
	$(PIP3) install -r requirements.txt

.PHONY: $(DB)
$(DB): | $(PYTHON3)
	DATABASE=$(DB) $(PYTHON3) -c\
	 "from periodo.commands import init_db; init_db()";

vocab.ttl: $(VOCAB_FILES) $(SHAPE_FILES)
	./bin/ttlcat $^ > $@

vocab.html: vocab.ttl
	highlight \
	--input=$< \
	--style=periodo.theme \
	--line-numbers \
	--anchors \
	--anchor-prefix='replaceme' \
	--doc-title='PeriodO vocabulary and shapes' \
	--inline-css \
	--font-size=12 \
	| sed 's/replaceme_/line-/' > $@

.PHONY: load_data
load_data: | $(PYTHON3)
ifeq ($(DATA),)
	$(error No data file provided. Run `make load_data DATA=/path/to/data/file`)
endif
	DATABASE=$(DB) $(PYTHON3) -c\
	 "from periodo.commands import load_data; load_data('$(DATA)')"

export.sql.gz:
ifeq ($(IMPORT_URL),)
	$(error No import URL provided. Run e.g. `make import IMPORT_URL=https://staging.perio.do/export.sql`)
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
	$(error No orcid provided. Run `make set_permissions ORCID=https://orcid.org/0000-1234 PERMISSIONS=perm1,perm2,perm3)
endif
	DATABASE=$(DB) $(PYTHON3) -c\
	 "from periodo.commands import set_permissions; set_permissions('$(ORCID)','$(PERMISSIONS)'.split(','))"

.PHONY: clean
clean:
	rm -rf $(VENV_DIR) vocab.html

.PHONY: test
test: | $(PYTHON3)
	TESTING=1 $(PYTEST) test

.PHONY: run
run: test
	$(PYTHON3) runserver.py
