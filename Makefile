VENV_DIR := venv
PIP3 := $(VENV_DIR)/bin/pip3
PYTHON3 := $(VENV_DIR)/bin/python3
DB := './db.sqlite'

CLIENT_REPO := '../periodo-client'
CLIENT_VERSION := latest

VOCAB_FILES := $(shell find vocab -name *.ttl)
SHAPE_FILES := $(shell find shapes -name *.ttl)

.PHONY: all
all: setup periodo/static/vocab.html $(DB)

$(PYTHON3):
	python3 -m venv $(VENV_DIR)

.PHONY: $(DB)
$(DB):
	$(PYTHON3) -c "from periodo.commands import init_db; init_db()";

periodo/static/vocab.ttl: $(VOCAB_FILES) $(SHAPE_FILES)
	mkdir -p periodo/static
	./bin/ttlcat $^ > $@

periodo/static/vocab.html: periodo/static/vocab.ttl
	highlight -i $< -o $@ -s zellner -l -a -T 'PeriodO vocabulary and shapes' --inline-css

.PHONY: load_data
load_data:
ifeq ($(DATA),)
	$(error No data file provided. Run `make load_data DATA=/path/to/data/file`)
endif
	$(PYTHON3) -c "from periodo.commands import load_data; load_data('$(DATA)')"

.PHONY: set_permissions
set_permissions:
ifeq ($(ORCID),)
	$(error No orcid provided. Run `make load_data ORCID=http://orcid.org/0000-1234 PERMISSIONS=perm1,perm2,perm3)
endif
	$(PYTHON3) -c "from periodo.commands import set_permissions; set_permissions('$(ORCID)','$(PERMISSIONS)'.split(','))"

.PHONY: setup
setup: $(PYTHON3) requirements.txt
	$(PIP3) install -r requirements.txt

.PHONY: clean
clean: clean_static_html
	rm -rf $(VENV_DIR)
	rm -rf periodo/static

.PHONY: clean_static_html
clean_static_html:
	if [ -L periodo/static/html ]; then rm periodo/static/html; else rm -rf periodo/static/html; fi

.PHONY: fetch_client
fetch_client: clean_static_html
	mkdir -p periodo/static/html
	TARBALL=`npm pack periodo-client@$(CLIENT_VERSION) | tail -n 1` && \
		tar xvzf $$TARBALL -C periodo/static/html --strip-components=1

.PHONY: fetch_latest_client
fetch_latest_client: fetch_client

.PHONY: link_client_repository
link_client_repository: clean_static_html
	ln -s $(abspath $(CLIENT_REPO)) periodo/static/html

.PHONY: test
test: setup periodo/static/vocab.ttl
	$(PYTHON3) -m unittest discover
