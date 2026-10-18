#!/usr/bin/env bash
# Demo write-behind inconsistency while a worker IS running.
#
# Starts a background worker with --demo-delay so you can enqueue + GET in the
# stale window (job dequeued but JSON/cache not updated yet, or cache still warm).
#
# Usage (from repo root):
#   ./scripts/demo-4b-enqueue-then-get.sh
#   ./scripts/demo-4b-enqueue-then-get.sh 101 8888
#   M4_DEMO_DELAY=5 ./scripts/demo-4b-enqueue-then-get.sh 101 8888
#
# Worker already running in another terminal (must use demo delay):
#   python labs/module-4-write-patterns/lab_4b_write_behind.py worker --demo-delay 3
#   SKIP_WORKER_START=1 ./scripts/demo-4b-enqueue-then-get.sh 101 8888

set -euo pipefail

REPO_ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$REPO_ROOT"

PRODUCT_ID="${1:-101}"
NEW_PRICE_CENTS="${2:-8888}"
DEMO_DELAY="${M4_DEMO_DELAY:-3}"
SKIP_WORKER_START="${SKIP_WORKER_START:-0}"

LAB="labs/module-4-write-patterns/lab_4b_write_behind.py"
DATA="labs/module-3-cache-aside/data/products.json"
WORKER_PID=""

if [[ -x ".venv/bin/python" ]]; then
  PYTHON=".venv/bin/python"
else
  PYTHON="python3"
fi

cleanup() {
  if [[ -n "$WORKER_PID" ]]; then
    kill "$WORKER_PID" 2>/dev/null || true
    wait "$WORKER_PID" 2>/dev/null || true
  fi
}
trap cleanup EXIT

json_price() {
  "$PYTHON" - "$PRODUCT_ID" "$DATA" <<'PY'
import json, sys
pid = int(sys.argv[1])
path = sys.argv[2]
with open(path, encoding="utf-8") as f:
    products = json.load(f)["products"]
for p in products:
    if int(p["id"]) == pid:
        print(p["price_cents"])
        sys.exit(0)
print("NOT_FOUND", file=sys.stderr)
sys.exit(1)
PY
}

redis_cache_price() {
  ./scripts/redis-cli.sh HGET "m4:product:${PRODUCT_ID}" price_cents 2>/dev/null || true
}

section() {
  echo ""
  echo "=== $* ==="
}

section "Setup"
echo "Product id:       ${PRODUCT_ID}"
echo "Enqueued price:   ${NEW_PRICE_CENTS}"
echo "Worker demo hold: ${DEMO_DELAY}s after dequeue (before JSON + cache DEL)"
echo "JSON on disk now: price_cents=$(json_price)"

if [[ "$SKIP_WORKER_START" == "1" ]]; then
  echo "Worker: using your existing process (SKIP_WORKER_START=1)"
else
  section "Start background worker"
  "$PYTHON" "$LAB" worker --demo-delay "$DEMO_DELAY" &
  WORKER_PID=$!
  echo "Worker pid=${WORKER_PID} (stopped automatically when this script exits)"
  sleep 0.5
fi

section "1) Warm cache (old price in m4:product)"
"$PYTHON" "$LAB" get "$PRODUCT_ID"
BEFORE_JSON="$(json_price)"
BEFORE_CACHE="$(redis_cache_price)"

section "2) Enqueue (API returns; durable JSON lags until worker flush)"
"$PYTHON" "$LAB" enqueue-price "$PRODUCT_ID" "$NEW_PRICE_CENTS"
"$PYTHON" "$LAB" queue-len

section "3) Immediate GET (inconsistency window)"
"$PYTHON" "$LAB" get "$PRODUCT_ID"
AFTER_JSON="$(json_price)"
AFTER_CACHE="$(redis_cache_price)"

section "4) Compare (enqueue vs ground truth vs what GET served)"
echo "Before enqueue — JSON: ${BEFORE_JSON}  cache: ${BEFORE_CACHE:-<no key>}"
echo "After immediate GET — JSON: ${AFTER_JSON}  cache: ${AFTER_CACHE:-<no key>}"
echo "Enqueued (pending) price: ${NEW_PRICE_CENTS}"
echo ""
if [[ "$AFTER_JSON" != "$NEW_PRICE_CENTS" ]] || [[ "${AFTER_CACHE:-}" == "$BEFORE_CACHE" && -n "${AFTER_CACHE:-}" ]]; then
  echo "=> Stale window visible: durable store and/or cache not yet at ${NEW_PRICE_CENTS}."
else
  echo "=> Window may have been too short; try M4_DEMO_DELAY=5 or a slower machine."
fi

section "5) Wait for worker flush, then GET again"
WAIT_SEC="$(python3 -c "import math; print(max(1, math.ceil(float('${DEMO_DELAY}') + 1)))")"
echo "Sleeping ${WAIT_SEC}s for demo hold + JSON write + cache invalidation..."
sleep "$WAIT_SEC"
"$PYTHON" "$LAB" get "$PRODUCT_ID"
echo "JSON on disk now: price_cents=$(json_price)"
