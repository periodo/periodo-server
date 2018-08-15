VENV_DIR := venv
PIP3 := $(VENV_DIR)/bin/pip3
PYTHON3 := $(VENV_DIR)/bin/python3
DB := ./db.sqlite

VOCAB_FILES := $(shell find vocab -name *.ttl)
SHAPE_FILES := $(shell find shapes -name *.ttl)

.PHONY: all
all: setup vocab.html $(DB)

$(PYTHON3):
	python3 -m venv $(VENV_DIR)

.PHONY: $(DB)
$(DB):
	DATABASE=$(DB) $(PYTHON3) -c\
	 "from periodo.commands import init_db; init_db()";

vocab.ttl: $(VOCAB_FILES) $(SHAPE_FILES)
	./bin/ttlcat $^ > $@

vocab.html: vocab.ttl
	highlight -i $< -o $@ -s zellner -l -a -T 'PeriodO vocabulary and shapes' --inline-css

.PHONY: load_data
load_data:
ifeq ($(DATA),)
	$(error No data file provided. Run `make load_data DATA=/path/to/data/file`)
endif
	$(PYTHON3) -c "from periodo.commands import load_data; load_data('$(DATA)')"

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
set_permissions:
ifeq ($(ORCID),)
	$(error No orcid provided. Run `make set_permissions ORCID=https://orcid.org/0000-1234 PERMISSIONS=perm1,perm2,perm3)
endif
	$(PYTHON3) -c "from periodo.commands import set_permissions; set_permissions('$(ORCID)','$(PERMISSIONS)'.split(','))"

.PHONY: setup
setup: $(PYTHON3) requirements.txt
	$(PIP3) install -q -r requirements.txt

.PHONY: clean
clean:
	rm -rf $(VENV_DIR)

.PHONY: test
test: setup
	$(PYTHON3) -m unittest discover

.PHONY: run
run: test
	$(PYTHON3) runserver.py
