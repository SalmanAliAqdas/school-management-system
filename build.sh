#!/usr/bin/env bash
set -o errexit
python -m pip install --upgrade 'pip>=26.2'
python -m pip install -r requirements.txt
python manage.py collectstatic --noinput
