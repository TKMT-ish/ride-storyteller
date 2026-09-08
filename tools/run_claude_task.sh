#!/bin/zsh
# Run one Claude Code task from a visible Terminal with a repository-local lock.
#
# This launcher intentionally starts a new explicit Claude session for each
# bounded task.  A follow-up may opt in to --resume with a known session ID.
# It refuses non-interactive execution so AI coding does not silently move to a
# hidden background process.

set -euo pipefail

script_path="$0"

usage() {
  print "Usage: $script_path --prompt-file PATH --included-plan-capacity-confirmed [--label TEXT] [--resume SESSION_ID]"
}

prompt_file=""
task_label="ride-storyteller-task"
resume_session_id=""
included_plan_capacity_confirmed=0

while (( $# > 0 )); do
  case "$1" in
    --prompt-file)
      (( $# >= 2 )) || { usage >&2; exit 64; }
      prompt_file="$2"
      shift 2
      ;;
    --label)
      (( $# >= 2 )) || { usage >&2; exit 64; }
      task_label="$2"
      shift 2
      ;;
    --resume)
      (( $# >= 2 )) || { usage >&2; exit 64; }
      resume_session_id="$2"
      shift 2
      ;;
    --included-plan-capacity-confirmed)
      included_plan_capacity_confirmed=1
      shift
      ;;
    --help|-h)
      usage
      exit 0
      ;;
    *)
      usage >&2
      exit 64
      ;;
  esac
done

[[ -n "$prompt_file" && -f "$prompt_file" && ! -L "$prompt_file" ]] || {
  print -u2 "Prompt file must be an existing non-symlink file."
  exit 66
}
[[ -t 0 && -t 1 && -t 2 ]] || {
  print -u2 "Claude Code tasks must be run from a visible interactive Terminal."
  exit 69
}
[[ "$included_plan_capacity_confirmed" -eq 1 ]] || {
  print -u2 "Before starting Claude, check /usage in an existing visible Claude Terminal."
  print -u2 "This runner permits only confirmed included-plan capacity; it must not be used for paid usage credits."
  exit 77
}
[[ -z "${ANTHROPIC_API_KEY:-}" ]] || {
  print -u2 "ANTHROPIC_API_KEY is set. This runner refuses API-key execution to avoid pay-as-you-go charges."
  exit 77
}

if [[ -n "$resume_session_id" && ! "$resume_session_id" =~ '^[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}$' ]]; then
  print -u2 "Resume session ID must be a UUID."
  exit 64
fi

lock_dir=".claude-busy"
if ! mkdir "$lock_dir" 2>/dev/null; then
  print -u2 "Claude Code lock already exists; no task was started."
  [[ -f "$lock_dir/owner" ]] && sed -n '1,4p' "$lock_dir/owner" >&2
  exit 75
fi

cleanup() {
  rm -f -- "$lock_dir/owner"
  rmdir -- "$lock_dir" 2>/dev/null || true
}
trap cleanup EXIT HUP INT TERM

umask 077
if [[ -n "$resume_session_id" ]]; then
  session_id="$resume_session_id"
  mode="resume"
else
  session_id="$(uuidgen | tr '[:upper:]' '[:lower:]')"
  mode="new"
fi
{
  print "pid=$$"
  print "started_at=$(date -u +%Y-%m-%dT%H:%M:%SZ)"
  print "mode=$mode"
  print "session_id=$session_id"
  print "label=$task_label"
} > "$lock_dir/owner"

print "Claude Code lock acquired ($mode session: $session_id)."
if [[ "$mode" == "resume" ]]; then
  claude --resume "$session_id" -p "$(<"$prompt_file")" --permission-mode auto
else
  claude --session-id "$session_id" -p "$(<"$prompt_file")" --permission-mode auto
fi
