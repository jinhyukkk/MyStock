#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")"

if [ ! -d backend/.venv ]; then
  echo "▸ 파이썬 가상환경 생성 중..."
  python3 -m venv backend/.venv
  backend/.venv/bin/pip install -q -e "backend[dev]"
fi

if [ ! -d frontend/dist ]; then
  echo "▸ 프론트엔드 빌드 중..."
  (cd frontend && npm install --silent && npm run build)
fi

echo "▸ MyStock 실행: http://localhost:8000"
cd backend && .venv/bin/uvicorn app.main:app --host 127.0.0.1 --port 8000
