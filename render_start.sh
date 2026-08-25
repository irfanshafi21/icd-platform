#!/bin/sh
set -eu

mkdir -p .streamlit

if [ -f /etc/secrets/secrets.toml ]; then
  cp /etc/secrets/secrets.toml .streamlit/secrets.toml
fi

exec streamlit run app.py   --server.address=0.0.0.0   --server.port="${PORT:-8501}"   --server.headless=true
