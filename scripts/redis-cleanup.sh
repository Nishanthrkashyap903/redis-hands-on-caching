#!/usr/bin/env bash
# Delete lab keys by pattern (SCAN + UNLINK). Run from repo root.
# Usage:
#   ./scripts/redis-cleanup.sh              # default lab prefixes
#   ./scripts/redis-cleanup.sh 'm2:*'       # one pattern
#   ./scripts/redis-cleanup.sh --dry-run    # print keys only
#   ./scripts/redis-cleanup.sh --flush-db   # entire DB 0 (destructive)

set -euo pipefail

CONTAINER="caching-redis"
DRY_RUN=false
FLUSH_DB=false
BATCH_SIZE=200
PATTERNS=()

while [[ $# -gt 0 ]]; do
  case "$1" in
    --dry-run)
      DRY_RUN=true
      shift
      ;;
    --flush-db)
      FLUSH_DB=true
      shift
      ;;
    -h|--help)
      sed -n '2,8p' "$0"
      exit 0
      ;;
    *)
      PATTERNS+=("$1")
      shift
      ;;
  esac
done

if ! docker ps --format '{{.Names}}' | grep -qx "$CONTAINER"; then
  echo "Container '$CONTAINER' is not running." >&2
  exit 1
fi

if [[ "$FLUSH_DB" == true ]]; then
  echo "FLUSHDB — removing ALL keys in database 0."
  if [[ "$DRY_RUN" == true ]]; then
    echo "(dry-run: would run FLUSHDB)"
    exit 0
  fi
  docker exec -i "$CONTAINER" redis-cli FLUSHDB
  echo "Done."
  exit 0
fi

if [[ ${#PATTERNS[@]} -eq 0 ]]; then
  PATTERNS=(
    "m2:*"
    "lab:*"
    "module0:*"
    "app:*"
    "m1:*"
  )
fi

# Full SCAN first, then delete. Deleting while SCAN streams can skip keys.
scan_matching_keys() {
  local pattern="$1"
  local out="$2"
  : >"$out"
  docker exec -i "$CONTAINER" redis-cli --scan --pattern "$pattern" >>"$out"
}

unlink_batch() {
  local -a batch=()
  local key
  for key in "$@"; do
    batch+=("$key")
  done
  [[ ${#batch[@]} -eq 0 ]] && return 0
  docker exec -i "$CONTAINER" redis-cli UNLINK "${batch[@]}" >/dev/null
}

delete_pattern() {
  local pattern="$1"
  local tmp
  tmp="$(mktemp)"
  trap 'rm -f "$tmp"' RETURN

  local removed=0
  local pass=0
  while true; do
    scan_matching_keys "$pattern" "$tmp"
    if [[ ! -s "$tmp" ]]; then
      break
    fi
    pass=$((pass + 1))
    local pass_count=0
    local -a batch=()

    while IFS= read -r key || [[ -n "${key:-}" ]]; do
      [[ -z "$key" ]] && continue
      if [[ "$DRY_RUN" == true ]]; then
        echo "$key" >&2
        pass_count=$((pass_count + 1))
        continue
      fi
      batch+=("$key")
      if [[ ${#batch[@]} -ge $BATCH_SIZE ]]; then
        unlink_batch "${batch[@]}"
        pass_count=$((pass_count + ${#batch[@]}))
        batch=()
      fi
    done <"$tmp"

    if [[ "$DRY_RUN" != true ]] && [[ ${#batch[@]} -gt 0 ]]; then
      unlink_batch "${batch[@]}"
      pass_count=$((pass_count + ${#batch[@]}))
    fi

    removed=$((removed + pass_count))
    [[ "$pass_count" -eq 0 ]] && break
    [[ "$pass" -ge 50 ]] && {
      echo "Warning: stopped after $pass passes for pattern $pattern (some keys may remain)." >&2
      break
    }
  done

  printf '%s\n' "$removed"
}

total=0
for pattern in "${PATTERNS[@]}"; do
  count="$(delete_pattern "$pattern")"
  echo "Pattern $pattern: $count key(s)"
  total=$((total + count))
done

if [[ "$DRY_RUN" == true ]]; then
  echo "Dry run — would remove $total key(s)."
else
  echo "Removed $total key(s)."
fi
