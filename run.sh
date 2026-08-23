#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")"

# .env 로드 (PORT, HOST_NAME, KRX_API_KEY 등) — 셸에서 직접 지정한 값이 우선
if [ -f .env ]; then set -a; . ./.env; set +a; fi

# *.localhost 는 브라우저가 127.0.0.1로 자동 해석 — hosts 파일 수정 불필요
HOST_NAME="${HOST_NAME:-mystock.localhost}"
PORT="${PORT:-80}"
# 서버가 실제로 바인딩할 주소. 기본은 로컬만 허용(127.0.0.1).
# Tailscale로 원격 접속하려면 .env에 BIND_HOST=<tailscale IP>를 지정 (tailscale ip -4로 확인)
BIND_HOST="${BIND_HOST:-127.0.0.1}"

fresh_venv=0
if [ ! -d backend/.venv ]; then
  echo "▸ 파이썬 가상환경 생성 중..."
  python3 -m venv backend/.venv
  fresh_venv=1
fi

# venv 실행 파일 위치: Unix는 bin, Windows(Git Bash)는 Scripts
if [ -d backend/.venv/Scripts ]; then VENV_BIN=Scripts; else VENV_BIN=bin; fi

if [ "$fresh_venv" = 1 ]; then
  "backend/.venv/$VENV_BIN/pip" install -q -e "backend[dev]"
fi

echo "▸ 프론트엔드 빌드 중..."
if [ ! -d frontend/node_modules ]; then (cd frontend && npm install --silent); fi
(cd frontend && npm run build)

url="http://$HOST_NAME"
[ "$PORT" = 80 ] || url="$url:$PORT"
echo "▸ MyStock 실행: $url"
cd backend && ".venv/$VENV_BIN/uvicorn" app.main:app --host "$BIND_HOST" --port "$PORT"
