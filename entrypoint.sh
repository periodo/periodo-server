#!/bin/sh
gunicorn --bind :8080 --workers 2 periodo:app
