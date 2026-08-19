#!/usr/bin/env bash
cd "$(dirname "$0")"
source .venv/bin/activate
mkdir -p logs
echo "=== $(date -u +%Y-%m-%dT%H:%M:%SZ) ===" >> logs/fetch.log
python -m src.fetch.run >> logs/fetch.log 2>&1