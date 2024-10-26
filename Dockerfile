ARG PYTHON_VERSION=3.12-slim

FROM --platform=linux/amd64 python:${PYTHON_VERSION}

RUN apt-get update && \
    DEBIAN_FRONTEND=noninteractive apt-get install -y \
    sqlite3 \
    rsync \
    && rm -rf /var/lib/apt/lists/*
ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1

WORKDIR /srv

RUN python -m venv venv

COPY requirements.txt /tmp/requirements.txt
RUN set -ex && \
    ./venv/bin/python -m pip install --upgrade pip && \
    ./venv/bin/python -m pip install -r /tmp/requirements.txt && \
    rm -rf /root/.cache/

COPY periodo periodo

ENTRYPOINT ["/srv/venv/bin/gunicorn", "--bind=[::]:8080", "--workers=2", "periodo:app"]
