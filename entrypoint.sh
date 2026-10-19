#!/bin/sh
gunicorn --bind :8080 --workers 2 --worker-class gthread --threads 4 periodo:app
