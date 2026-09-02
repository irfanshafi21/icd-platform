#!/bin/sh
set -eu

mkdir -p .streamlit
if [ -f /etc/secrets/secrets.toml ]; then
  cp /etc/secrets/secrets.toml .streamlit/secrets.toml
fi

exec uvicorn web_app:app --host 0.0.0.0 --port "${PORT:-8501}" --workers 1
