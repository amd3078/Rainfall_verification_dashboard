#!/usr/bin/env bash
# Deploy the rainfall verification dashboard on a server/VM.
# Creates a venv, installs deps, launches Streamlit (no timeout, headless, 0.0.0.0:PORT).
#
# Usage:
#   ./deploy.sh                         # foreground (Ctrl-C to stop)
#   ./deploy.sh --background            # nohup, logs to dashboard.log, PID in dashboard.pid
#   PORT=8600 ./deploy.sh               # override port
#   VERIF_DATA_DIR=/data/fcst VERIF_OBS=/data/obs.nc ./deploy.sh   # point at real data
#
# Stop background:  kill "$(cat dashboard.pid)"
set -euo pipefail
HERE="$(cd "$(dirname "$0")" && pwd)"; cd "$HERE"

# load .env if present (data paths, Firebase creds, PORT)
if [ -f .env ]; then set -a; . ./.env; set +a; echo "[deploy] loaded .env"; fi

PORT="${PORT:-8501}"
PY="${PYTHON:-python3}"
VENV="${VENV:-.venv}"

# 1. venv + deps
if [ ! -d "$VENV" ]; then
  echo "[deploy] creating venv $VENV"
  "$PY" -m venv "$VENV"
fi
# shellcheck disable=SC1091
source "$VENV/bin/activate"
echo "[deploy] installing requirements"
pip install -q --upgrade pip
pip install -q -r requirements.txt

# 2. demo data if none present and no real data configured
if [ -z "${VERIF_DATA_DIR:-}" ] && [ ! -f demo_data/obs_demo.nc ]; then
  echo "[deploy] generating demo data"
  python make_demo_data.py
fi

# 3. sanity check
echo "[deploy] self-test"
python app.py --selftest >/dev/null 2>&1 && echo "[deploy] self-test OK" || echo "[deploy] self-test warnings (non-fatal)"

# 4. launch
echo "[deploy] starting on http://0.0.0.0:$PORT"
CMD=(streamlit run app.py --server.port "$PORT" --server.address 0.0.0.0 --server.headless true)
if [ "${1:-}" = "--background" ]; then
  nohup "${CMD[@]}" > dashboard.log 2>&1 &
  echo $! > dashboard.pid
  echo "[deploy] background PID $(cat dashboard.pid), logs -> dashboard.log"
else
  exec "${CMD[@]}"
fi
