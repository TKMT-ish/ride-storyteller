#!/bin/zsh
# Second layer of the autonomy loop: runs the same prompt headless when the
# desktop app's scheduled task has not run recently (app closed, run stuck).
# Layers: (1) desktop scheduled task, (2) this launchd watchdog, (3) cloud routine.
#
# The lock and the heartbeat belong to the RUN, not to this launcher. The prompt
# (SKILL.md) tells the run to mkdir the lock, touch the heartbeat, and rm the lock
# on exit. When this script took the lock first, the run saw a fresh lock, concluded
# another layer was working, and no-opped every single time -- while the heartbeat
# this script had touched hid the outage from the next watchdog. Do not add either back.
set -u
ROOT="/Users/tkmt/Projects/Ride Storyteller"
PROMPT_FILE="$HOME/.claude/scheduled-tasks/ride-storyteller-autonomous-loop/SKILL.md"
HEARTBEAT="$ROOT/.autonomy/heartbeat"
LOCK="$ROOT/.autonomy/lock"
LOG="$ROOT/.autonomy/watchdog.log"
STALE_S=2700          # run if no heartbeat for 45 min
LOCK_STALE_S=7200     # a lock older than 2 h belongs to a dead run
cd "$ROOT" || exit 1
now=$(date +%s)
if [[ -f "$HEARTBEAT" ]]; then
  age=$(( now - $(stat -f %m "$HEARTBEAT") ))
  if (( age < STALE_S )); then echo "$(date '+%F %T') heartbeat ${age}s ago; nothing to do" >> "$LOG"; exit 0; fi
fi
# Skip only while another layer genuinely holds the lock; the run itself takes it.
if [[ -d "$LOCK" ]]; then
  lage=$(( now - $(stat -f %m "$LOCK") ))
  if (( lage < LOCK_STALE_S )); then echo "$(date '+%F %T') lock held by another layer (${lage}s); skip" >> "$LOG"; exit 0; fi
  echo "$(date '+%F %T') lock stale (${lage}s); removing" >> "$LOG"
  rm -rf "$LOCK"
fi
echo "$(date '+%F %T') watchdog run start" >> "$LOG"
# The prompt is the task's SKILL.md body (after the frontmatter).
prompt=$(awk 'BEGIN{fm=0} /^---$/{fm++; next} fm>=2{print}' "$PROMPT_FILE")
[[ -z "$prompt" ]] && prompt=$(cat "$PROMPT_FILE")
/opt/homebrew/bin/claude -p "$prompt" --dangerously-skip-permissions --max-turns 80 >> "$LOG" 2>&1
rc=$?
echo "$(date '+%F %T') watchdog run end rc=$rc" >> "$LOG"
