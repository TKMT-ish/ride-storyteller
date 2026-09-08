#!/bin/bash
# Take one day of the trip from GPX and footage to a finished film.
#
#   scripts/trip/process-day.sh <N>            e.g. 3 for day 3
#
# Reads private-media/input/videos/dayN/*.gpx and the footage folder in
# RIDE_TRIP_VIDEO_ROOT (the external drive; read only, nothing is copied).
# Stops, and says why, when the clock offset is ambiguous or any step fails.
# Every step is idempotent: a package already past a step skips it.
#
# Money: only `judge` and `rank` spend (Gemini via the owner's own bucket).
# The stride is fixed at 60 s (plan B, 2026-09-05) so a day costs about
# half of what day 2 did. The spend of each day is appended to the log.
set -euo pipefail

N="${1:?day number}"
ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
cd "$ROOT"
PY="$ROOT/.venv/bin/python"
DAY_DIR="$ROOT/private-media/input/videos/day$N"
VIDEO_ROOT="${RIDE_TRIP_VIDEO_ROOT:?set RIDE_TRIP_VIDEO_ROOT to the footage folder}"
PKG="$ROOT/private-media/work/day-$N-v1"
BUCKET="${RIDE_ANALYSIS_BUCKET:-ride-storyteller-analysis}"
STRIDE="${RIDE_TRIP_STRIDE_S:-60}"
# Place names for the chapter titles: the country's language, so one title is one script.
export RIDE_PLACE_LANGUAGE="${RIDE_PLACE_LANGUAGE:-en}"
LOG_DIR="$ROOT/.autonomy/trip"
mkdir -p "$LOG_DIR"
LOG="$LOG_DIR/day-$N.log"

say() { printf '%s day%s %s\n' "$(date '+%H:%M:%S')" "$N" "$*" | tee -a "$LOG"; }

GPX="$(find "$DAY_DIR" -maxdepth 1 -iname '*.gpx' | head -1)"
[ -n "$GPX" ] || { say "no GPX in $DAY_DIR"; exit 2; }
[ -d "$VIDEO_ROOT" ] || { say "footage folder not mounted: $VIDEO_ROOT"; exit 2; }

# 1. The clock offset: first from the cameras' own GPS (to the second, no
#    time-zone guess), else from where the recordings fall inside the ride --
#    and that only when it is unambiguous, because a folder holding every day
#    of a trip lets a wrong shift pull another day's recordings inside.
if [ ! -f "$PKG/local-pipeline-inputs.json" ]; then
  say "measuring the clock offset from the recordings' GPS"
  GPSCLOCK="$LOG_DIR/day-$N-gpsclock.json"
  if "$PY" -m app.gopro_gps "$GPX" "$VIDEO_ROOT" > "$GPSCLOCK" 2>>"$LOG"; then
    OFFSET="$("$PY" -c "import json,sys;print(json.load(open(sys.argv[1]))['proposed']['offset_s'])" "$GPSCLOCK")"
    DETAIL="$("$PY" -c "import json,sys;p=json.load(open(sys.argv[1]))['proposed'];print(p['recordings_inside'],'inside,',p['recordings_measured'],'measured, spread',p['spread_s'],'s')" "$GPSCLOCK")"
    UNAMBIGUOUS="$("$PY" -c "import json,sys;print(json.load(open(sys.argv[1]))['is_unambiguous'])" "$GPSCLOCK")"
    say "GPS clock: ${OFFSET}s ($DETAIL), unambiguous: $UNAMBIGUOUS"
    if [ "$UNAMBIGUOUS" != "True" ]; then
      say "the recordings' clocks disagree; stopping so a person can look (see $GPSCLOCK)"
      exit 3
    fi
  else
    say "no usable GPS in the recordings; falling back to the containment proposal"
    PROPOSAL="$LOG_DIR/day-$N-offset.json"
    "$PY" -m app.clock_offset "$GPX" "$VIDEO_ROOT" > "$PROPOSAL"
    UNAMBIGUOUS="$("$PY" -c "import json,sys;print(json.load(open(sys.argv[1]))['is_unambiguous'])" "$PROPOSAL")"
    OFFSET="$("$PY" -c "import json,sys;print(json.load(open(sys.argv[1]))['proposed']['offset_s'])" "$PROPOSAL")"
    say "offset proposal: ${OFFSET}s, unambiguous: $UNAMBIGUOUS"
    if [ "$UNAMBIGUOUS" != "True" ]; then
      say "the offset is ambiguous; stopping so a person can choose (see $PROPOSAL)"
      exit 3
    fi
  fi
  # 2. The package: catalogue, matching, review clips skipped (the judgement decides).
  say "building the package at $STRIDE s stride"
  "$PY" -m app.local_pipeline "$GPX" "$VIDEO_ROOT" --output "$PKG" \
    --clock-offset-s "$OFFSET" --clock-offset-confirmed --target-duration-s 300 \
    --skip-review-clips >> "$LOG" 2>&1
else
  say "package exists; keeping it"
fi

# 3. Plan at the fixed stride (writes the setting into the package).
"$PY" -m app.analysis_cli plan "$PKG" --stride-s "$STRIDE" > "$LOG_DIR/day-$N-plan.json"
COST="$("$PY" -c "import json,sys;d=json.load(open(sys.argv[1]));print(d['candidate_count'],'windows, about', d['cost']['total_jpy'],'JPY')" "$LOG_DIR/day-$N-plan.json")"
say "plan: $COST"

# 4. Copies (free, local, slow).
if [ ! -f "$PKG/gemini-video-analysis.json" ]; then
  say "making the copies to send"
  "$PY" -m app.analysis_cli preflight "$PKG" > "$LOG_DIR/day-$N-preflight.json"
  READY="$("$PY" -c "import json,sys;print(json.load(open(sys.argv[1]))['preflight']['ready'])" "$LOG_DIR/day-$N-preflight.json")"
  [ "$READY" = "True" ] || { say "preflight not ready (see $LOG_DIR/day-$N-preflight.json)"; exit 4; }
  # 5. The judgement (spends).
  say "buying the judgement"
  "$PY" -m app.analysis_cli judge "$PKG" --bucket "$BUCKET" --prefix "day-$N-v1" --i-approve-spending > "$LOG_DIR/day-$N-judge.json"
  say "judged: $("$PY" -c "import json,sys;d=json.load(open(sys.argv[1]));print(d['newly_bought'],'bought,', d['carried_from_earlier_attempt'],'carried')" "$LOG_DIR/day-$N-judge.json")"
else
  say "judgement exists; not buying again"
fi

# 6. The comparative ranking around the cut (spends a little).
if [ ! -f "$PKG/gemini-window-ranking.json" ]; then
  say "buying the ranking"
  "$PY" -m app.analysis_cli rank "$PKG" --bucket "$BUCKET" --prefix "day-$N-v1" --i-approve-spending > "$LOG_DIR/day-$N-rank.json" || say "ranking failed or was refused; the film is cut without it"
fi

# 7. The film (free, local).
say "cutting the film"
"$PY" -m app.private_journey_film "$PKG" --overwrite > "$LOG_DIR/day-$N-film.json" 2>> "$LOG"
say "film: $(ffprobe -v error -show_entries format=duration,size -of csv=p=0 "$PKG/ride-storyteller-story-film.mp4") map=$("$PY" -c "import json,sys;print(json.load(open(sys.argv[1])).get('map_background'))" "$LOG_DIR/day-$N-film.json")"
say "done"
