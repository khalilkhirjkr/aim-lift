#!/usr/bin/env bash
# Build step for the deployment host (Render: "Build Command").
set -o errexit

pip install -r requirements.txt
python manage.py collectstatic --noinput
python manage.py migrate --noinput
