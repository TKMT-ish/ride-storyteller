#!/bin/bash
# Run process-day.sh for a range of days, in order, stopping at the first day that stops.
#   scripts/trip/process-days.sh 3 12
set -euo pipefail
FIRST="${1:?first day}"; LAST="${2:?last day}"
ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
for N in $(seq "$FIRST" "$LAST"); do
  if ! "$ROOT/scripts/trip/process-day.sh" "$N"; then
    echo "stopped at day $N; see $ROOT/.autonomy/trip/day-$N.log"
    exit 1
  fi
done
echo "days $FIRST to $LAST done"
