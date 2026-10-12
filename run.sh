#!/usr/bin/env bash
# Docker'sız yerel çalıştırma (Linux/macOS). Windows için README'ye bak.
set -e
cd "$(dirname "$0")"
if [ ! -d .venv ]; then
  python3.11 -m venv .venv 2>/dev/null || python3 -m venv .venv
fi
source .venv/bin/activate
pip install -q -r backend/requirements.txt
if [ ! -d frontend/dist ]; then
  (cd frontend && npm install --silent && npm run build)
fi
export FRONTEND_DIST="$(pwd)/frontend/dist"
cd backend
exec uvicorn app.main:app --host 0.0.0.0 --port 8000
