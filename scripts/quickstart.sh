#!/usr/bin/env bash
set -euo pipefail
python3 -m venv .venv
. .venv/bin/activate
python -m pip install -e '.[dev]'
flipper-rag ingest --path knowledge/starter
printf '\nReady. To index official sites: flipper-rag sync --web\n'
printf 'Run web UI: uvicorn flipper_rag.api:app --host 127.0.0.1 --port 8000\n'
