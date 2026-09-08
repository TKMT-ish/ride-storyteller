"""Bridge approved highlight candidates into the GPS-event story pipeline.

See docs/highlight-story-bridge-design-ja.md for the full design. In short:
GPS-derived events and video-derived highlight candidates currently reach
confirmed evidence through two separate contracts (`app.video.review` and
`app.video.highlight_review`). This module converts an *approved* highlight
candidate (`HighlightReviewStatus.APPROVED`) into a `GpsEvent` so it can join
the same Story Plan / candidate-edit / evidence-review pipeline as any
GPS-derived event, without changing either existing contract.

Persistence and what this module deliberately does not carry
---------------------------------------------------------------
`HighlightBridgeCandidate` is a narrow, privacy-conservative projection of a
`QualitySelection` — only what synthesizing a `GpsEvent` actually needs:
an opaque candidate ID, method, rank, absolute time window, location, the
interest lane(s) that qualified it, and the score used as importance_hint.

It excludes the source `asset_id`, raw FFmpeg/GPMF window metrics, and Vision
frame classifications. None of those are needed to place a candidate on the
route: two selections of the same physical window always share the same
absolute time window regardless of method, so event identity and duplicate
collapsing use the time window instead of `asset_id`. Persisting Vision's
semantic classification labels would also go beyond what comparable private
artifacts already store — neither
`highlight_quality.export_quality_research_manifest` nor
`metric_cache.PrivateMetricCache` persists Vision output or source
identifiers, and the handoff doc records Vision output as intentionally not
reused across runs (see docs/current-system-handoff-ja.md §12).

This narrow shape is what makes cross-process persistence
(`write_highlight_bridge_candidates` / `load_highlight_bridge_candidates`)
practical: `QualitySelection` itself (Vision frames, GPMF summaries, raw
window features) has no serialization of its own today, and giving it one
was not necessary once the bridge's actual requirements were this small.

Scope of this increment
------------------------
A highlight candidate whose absolute time window does not overlap any
existing `GpsEvent` is promoted to a new event (`build_highlight_gps_events`).
A candidate that does overlap an already-*resolved* clip instead reinforces
that clip's interval (`reinforce_resolved_clips_with_highlights`), per
docs/highlight-story-bridge-design-ja.md §7-5: real-media testing on
2026-09-02 found that on an actual ride every highlight candidate overlapped
an existing GPS event, so the "add a new event" half alone added nothing —
reinforcement is where the real value is.

Reinforcement is deliberately conservative and fails closed on every
ambiguous case, keeping the original resolved interval unchanged rather than
guessing:

- an unmatched (`NOT_FOUND`) clip is left as-is (nothing to reinforce),
- a candidate whose absolute window is not fully contained within the same
  catalog entry the clip was resolved against (its "asset identity") is
  dropped rather than assumed to be the same recording,
- when more than one candidate overlaps the same resolved clip, they are
  only compared, and one chosen automatically, when all of them share the
  same `QualitySelectionMethod` (score is not comparable across methods) and
  the lowest `rank` among them is unique; a mix of methods or a tied lowest
  rank has no automatic answer (see `_select_unambiguous_candidate`) —
  unless an explicit `HighlightReinforcementSelection` resolves it (below),
- a candidate that does not make the resolved interval strictly narrower
  (the intersection would be equal to or wider than the original, or empty)
  changes nothing.

Only `start_offset_s`/`end_offset_s` are ever narrowed, and always to a
subset of the original interval. `asset_id`, `status`, evidence
decisions, the automatic-confirmation policy (docs/current-system-handoff-ja.md
§5), and the clock-offset human-confirmation requirement are all untouched.
Both paths are wired into `app.local_pipeline.prepare_local_review_package`
via its `highlight_bridge_candidates_path` parameter.

Explicit reinforcement selections (private-only, no UI yet)
-------------------------------------------------------------
When automatic priority is ambiguous (a mix of methods, or a tied rank), a
future private UI needs a way to record a human's explicit choice: "for this
resolved clip's event, use this specific candidate." `HighlightReinforcementSelection`
is that contract's only content — an `(event_id, candidate_id)` pairing held
only in a private local artifact. It carries no free text, coordinates, path, file
name, video content, or credential.

`reinforce_resolved_clips_with_highlights` accepts an optional
`HighlightReinforcementSelectionSet`. For a clip whose event has a recorded
selection, the referenced candidate takes priority over the automatic
`_select_unambiguous_candidate` outcome (whether or not the automatic path
would itself have found an unambiguous answer) — but *only* if that
candidate independently passes every safety check the automatic path already
enforces: asset identity, absolute-time overlap, and strict narrowing. A
selection that fails any of those (unknown candidate, wrong/stale/
asset-mismatched candidate, or one that would not narrow) is not a reason to
fall back to the automatic pick either: the clip is left unchanged, exactly
like the automatic path's own fail-closed cases. A clip whose event has no
recorded selection falls back to the automatic path unchanged. When no
selection set is supplied at all (the default), behaviour is byte-for-byte
identical to before this contract existed.

No web endpoint or renderer reads or writes this contract yet — that is a
separate, later task.

Listing unresolved conflicts (private-only, no UI yet)
---------------------------------------------------------
Before a human can record a `HighlightReinforcementSelection`, a future
private UI needs to know which clips actually need one.
`find_highlight_reinforcement_conflicts` computes exactly that: for each
resolved clip, it applies the same asset-identity, absolute-time-overlap,
and strict-narrowing checks `reinforce_resolved_clips_with_highlights` itself
applies (per-candidate, not just to whichever one ends up chosen), then
keeps only the clips where the same `_select_unambiguous_candidate` rule
still cannot pick a unique winner (a mix of methods, or a tied lowest rank).
A clip with zero valid candidates, or with a valid set that already resolves
automatically, is not a conflict — there is nothing for a human to decide.

Each `HighlightReinforcementConflict` names one candidate competing for one
clip's event: `event_id`, `candidate_id`, `method`, `rank`. Nothing else —
no location, path, asset name, video content, absolute time, offset, score,
or credential. This function takes no `HighlightReinforcementSelectionSet`
and is unaware of any existing selection; it only answers "does this clip
still need a human decision," leaving the deciding and recording to that
separate contract.
"""

from __future__ import annotations

import hashlib
import json
import os
from dataclasses import dataclass, replace
from datetime import UTC, datetime, timedelta
from pathlib import Path
from tempfile import mkstemp

from app.contracts import GpsEvent, Location, VideoQuery

from .catalog import ResolvedCandidateClip, VideoCatalog, VideoCatalogEntry, VideoMatchStatus
from .highlight_quality import InterestLane, QualitySelection, QualitySelectionMethod
from .highlight_review import HighlightReviewResult, highlight_review_candidate_id

HIGHLIGHT_EVENT_TYPE = "visual_highlight"
HIGHLIGHT_BRIDGE_CANDIDATES_SCHEMA_VERSION = "local-highlight-bridge-candidates-v1"


class HighlightStoryBridgeError(ValueError):
    """Raised when a highlight candidate cannot be promoted to a GpsEvent."""


@dataclass(frozen=True)
class HighlightBridgeCandidate:
    """The narrow view of one approved highlight candidate the bridge needs.

    See the module docstring for what this deliberately excludes.
    """

    candidate_id: str
    method: QualitySelectionMethod
    rank: int
    start_time: datetime
    duration_s: float
    location: Location
    interest_lanes: tuple[InterestLane, ...]
    score: float

    def __post_init__(self) -> None:
        if not self.candidate_id or self.rank <= 0:
            raise ValueError("bridge candidate ID and positive rank are required")
        if self.start_time.tzinfo is None:
            raise ValueError("bridge candidate start_time must be timezone-aware")
        if self.duration_s <= 0:
            raise ValueError("bridge candidate duration_s must be positive")
        if not self.interest_lanes or len(self.interest_lanes) != len(set(self.interest_lanes)):
            raise ValueError("bridge candidate requires unique, non-empty interest lanes")
        if not 0.0 <= self.score <= 1.0:
            raise ValueError("bridge candidate score must be between 0.0 and 1.0")

    @property
    def end_time(self) -> datetime:
        return self.start_time + timedelta(seconds=self.duration_s)

    def to_dict(self) -> dict[str, object]:
        return {
            "candidate_id": self.candidate_id,
            "method": self.method.value,
            "rank": self.rank,
            "start_time": self.start_time.isoformat().replace("+00:00", "Z"),
            "duration_s": self.duration_s,
            "latitude": self.location.latitude,
            "longitude": self.location.longitude,
            "interest_lanes": [lane.value for lane in self.interest_lanes],
            "score": self.score,
        }


@dataclass(frozen=True)
class HighlightBridgeCandidateSet:
    candidates: tuple[HighlightBridgeCandidate, ...]

    def __post_init__(self) -> None:
        ids = [candidate.candidate_id for candidate in self.candidates]
        if len(ids) != len(set(ids)):
            raise ValueError("bridge candidate IDs must be unique")

    def to_dict(self) -> dict[str, object]:
        return {
            "schema_version": HIGHLIGHT_BRIDGE_CANDIDATES_SCHEMA_VERSION,
            "candidates": [candidate.to_dict() for candidate in self.candidates],
        }


def highlight_bridge_candidate_from_selection(
    selection: QualitySelection,
) -> HighlightBridgeCandidate:
    """Project one `QualitySelection` down to what the bridge actually needs.

    Raises `HighlightStoryBridgeError` if the candidate has no recorded GPS
    location (only possible for a window whose route coverage was too sparse
    for `highlight_discovery._gps_features` to report a midpoint location).
    """
    window = selection.scored.evidence.window
    if window.latitude is None or window.longitude is None:
        raise HighlightStoryBridgeError("highlight candidate has no recorded GPS location")
    # `timeline_s` is already an absolute GPS-clock Unix timestamp, not a
    # video-relative offset (see highlight_discovery._features_for_source).
    start_time = datetime.fromtimestamp(window.timeline_s, tz=UTC)
    return HighlightBridgeCandidate(
        candidate_id=highlight_review_candidate_id(selection),
        method=selection.method,
        rank=selection.rank,
        start_time=start_time,
        duration_s=window.duration_s,
        location=Location(window.latitude, window.longitude),
        interest_lanes=tuple(dict.fromkeys(selection.scored.interest_lanes)),
        score=max(0.0, min(1.0, selection.scored.score_for(selection.method))),
    )


def export_highlight_bridge_candidates(
    selections: dict[QualitySelectionMethod, tuple[QualitySelection, ...]],
    review_result: HighlightReviewResult,
) -> HighlightBridgeCandidateSet:
    """Project every review-approved candidate with a known location.

    A manual rejection recorded in `review_result` always wins: only
    candidates in `review_result.approved_candidate_ids` are considered. A
    candidate with no recorded location is silently skipped rather than
    failing the whole export, since sparse route coverage is expected at the
    edges of a recording.
    """
    approved_ids = set(review_result.approved_candidate_ids)
    candidates: list[HighlightBridgeCandidate] = []
    for method in QualitySelectionMethod:
        for selection in selections.get(method, ()):
            if highlight_review_candidate_id(selection) not in approved_ids:
                continue
            try:
                candidates.append(highlight_bridge_candidate_from_selection(selection))
            except HighlightStoryBridgeError:
                continue
    return HighlightBridgeCandidateSet(tuple(candidates))


def load_highlight_bridge_candidates(path: Path) -> HighlightBridgeCandidateSet:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if payload.get("schema_version") != HIGHLIGHT_BRIDGE_CANDIDATES_SCHEMA_VERSION:
        raise ValueError("unsupported highlight bridge candidate schema")
    return HighlightBridgeCandidateSet(
        tuple(
            HighlightBridgeCandidate(
                candidate_id=item["candidate_id"],
                method=QualitySelectionMethod(item["method"]),
                rank=int(item["rank"]),
                start_time=datetime.fromisoformat(item["start_time"].replace("Z", "+00:00")),
                duration_s=float(item["duration_s"]),
                location=Location(float(item["latitude"]), float(item["longitude"])),
                interest_lanes=tuple(InterestLane(lane) for lane in item["interest_lanes"]),
                score=float(item["score"]),
            )
            for item in payload.get("candidates", [])
        )
    )


def write_highlight_bridge_candidates(
    output_path: Path,
    candidate_set: HighlightBridgeCandidateSet,
    *,
    overwrite: bool = True,
) -> Path:
    """Persist the bridge candidate set. Derived, non-human-edited data, so a
    rerun overwrites it by default rather than preserving a stale prior
    version.
    """
    if output_path.exists() and not overwrite:
        raise FileExistsError(
            "highlight bridge candidates already exist; choose a new path or pass overwrite=True"
        )
    output_path.parent.mkdir(parents=True, exist_ok=True)
    file_descriptor, temporary_name = mkstemp(
        dir=output_path.parent,
        prefix=f".{output_path.name}.",
        suffix=".tmp",
        text=True,
    )
    temporary_path = Path(temporary_name)
    try:
        with os.fdopen(file_descriptor, "w", encoding="utf-8") as handle:
            handle.write(json.dumps(candidate_set.to_dict(), ensure_ascii=False, indent=2) + "\n")
        os.replace(temporary_path, output_path)
    except BaseException:
        temporary_path.unlink(missing_ok=True)
        raise
    return output_path


def _highlight_event_id(candidate: HighlightBridgeCandidate) -> str:
    """Derive a stable event ID from the candidate's time window alone.

    The same physical window is often approved under more than one selection
    method; deriving the ID from the time window lets those duplicates
    collapse to one event instead of producing near-identical events.
    """
    material = f"{candidate.start_time.timestamp():.3f}:{candidate.duration_s:.3f}"
    return f"highlight-event-{hashlib.sha256(material.encode('utf-8')).hexdigest()[:16]}"


def overlaps_existing_event(
    candidate: HighlightBridgeCandidate, existing_events: tuple[GpsEvent, ...]
) -> bool:
    """Return True if the candidate's absolute time window overlaps any event."""
    return any(
        candidate.start_time < event.end_time and event.start_time < candidate.end_time
        for event in existing_events
    )


def build_highlight_gps_event(candidate: HighlightBridgeCandidate) -> GpsEvent:
    """Synthesize one video-originated GpsEvent from an approved candidate."""
    return GpsEvent(
        event_id=_highlight_event_id(candidate),
        event_type=HIGHLIGHT_EVENT_TYPE,
        start_time=candidate.start_time,
        end_time=candidate.end_time,
        location=candidate.location,
        importance_hint=candidate.score,
        evidence=tuple(lane.value for lane in candidate.interest_lanes),
        video_query=VideoQuery(
            asset_name_hint=HIGHLIGHT_EVENT_TYPE,
            clip_start_offset_s=0.0,
            clip_end_offset_s=candidate.duration_s,
        ),
    )


def build_highlight_gps_events(
    candidates: tuple[HighlightBridgeCandidate, ...],
    existing_events: tuple[GpsEvent, ...],
) -> tuple[GpsEvent, ...]:
    """Promote every non-overlapping bridge candidate to a GpsEvent.

    Candidates whose window overlaps an existing GPS event are skipped (see
    module docstring). The same physical window approved under more than one
    method collapses to a single event.
    """
    events_by_id: dict[str, GpsEvent] = {}
    for candidate in candidates:
        if overlaps_existing_event(candidate, existing_events):
            continue
        event = build_highlight_gps_event(candidate)
        events_by_id.setdefault(event.event_id, event)
    return tuple(
        sorted(events_by_id.values(), key=lambda event: (event.start_time, event.event_id))
    )


HIGHLIGHT_REINFORCEMENT_SELECTION_SCHEMA_VERSION = "local-highlight-reinforcement-selection-v1"


@dataclass(frozen=True)
class HighlightReinforcementSelection:
    """An explicit choice: for this resolved clip's event, use this candidate.

    Both fields are private local identifiers (a `GpsEvent.event_id` and a
    `highlight_review_candidate_id` hash). This carries nothing else — no
    free text, coordinates, path, file name, video content, or credential.
    """

    event_id: str
    candidate_id: str

    def __post_init__(self) -> None:
        if not self.event_id or not self.candidate_id:
            raise ValueError("reinforcement selection requires event_id and candidate_id")

    def to_dict(self) -> dict[str, object]:
        return {"event_id": self.event_id, "candidate_id": self.candidate_id}


@dataclass(frozen=True)
class HighlightReinforcementSelectionSet:
    """At most one explicit selection per event and per candidate."""

    selections: tuple[HighlightReinforcementSelection, ...]

    def __post_init__(self) -> None:
        event_ids = [selection.event_id for selection in self.selections]
        candidate_ids = [selection.candidate_id for selection in self.selections]
        if len(event_ids) != len(set(event_ids)) or len(candidate_ids) != len(set(candidate_ids)):
            raise ValueError("reinforcement selections must have unique event_id and candidate_id")

    def to_dict(self) -> dict[str, object]:
        return {
            "schema_version": HIGHLIGHT_REINFORCEMENT_SELECTION_SCHEMA_VERSION,
            "selections": [selection.to_dict() for selection in self.selections],
        }

    def candidate_id_for(self, event_id: str) -> str | None:
        for selection in self.selections:
            if selection.event_id == event_id:
                return selection.candidate_id
        return None


def load_highlight_reinforcement_selections(path: Path) -> HighlightReinforcementSelectionSet:
    """Load an explicit selection set, failing closed on anything unexpected.

    Rejects a symlinked or missing path, malformed JSON, an unsupported or
    missing schema version, any top-level or per-selection field other than
    exactly what this contract defines, non-string identifiers, and more
    than one selection for the same event_id.
    """
    if path.is_symlink() or not path.is_file():
        raise ValueError("highlight reinforcement selections are unavailable")
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise ValueError("highlight reinforcement selections are unreadable") from error
    if not isinstance(payload, dict) or set(payload) != {"schema_version", "selections"}:
        raise ValueError("highlight reinforcement selections have an invalid schema")
    if payload["schema_version"] != HIGHLIGHT_REINFORCEMENT_SELECTION_SCHEMA_VERSION:
        raise ValueError("unsupported highlight reinforcement selection schema")
    raw_selections = payload["selections"]
    if not isinstance(raw_selections, list):
        raise ValueError("highlight reinforcement selections have an invalid schema")
    selections: list[HighlightReinforcementSelection] = []
    for item in raw_selections:
        if not isinstance(item, dict) or set(item) != {"event_id", "candidate_id"}:
            raise ValueError("highlight reinforcement selections have an invalid schema")
        event_id, candidate_id = item["event_id"], item["candidate_id"]
        if not isinstance(event_id, str) or not isinstance(candidate_id, str):
            raise ValueError("highlight reinforcement selections have an invalid schema")
        selections.append(
            HighlightReinforcementSelection(event_id=event_id, candidate_id=candidate_id)
        )
    return HighlightReinforcementSelectionSet(tuple(selections))


def write_highlight_reinforcement_selections(
    output_path: Path,
    selection_set: HighlightReinforcementSelectionSet,
    *,
    overwrite: bool = False,
) -> Path:
    """Persist an explicit selection set atomically to a caller-chosen path.

    Defaults to not overwriting: unlike the derived, regenerate-each-run
    bridge candidate/borderline outputs, this represents a deliberate human
    choice a rerun must not silently discard.
    """
    if output_path.is_symlink():
        raise ValueError("highlight reinforcement selections path must not be a symlink")
    if output_path.exists() and not overwrite:
        raise FileExistsError(
            "highlight reinforcement selections already exist; choose a new path or pass "
            "overwrite=True"
        )
    output_path.parent.mkdir(parents=True, exist_ok=True)
    file_descriptor, temporary_name = mkstemp(
        dir=output_path.parent,
        prefix=f".{output_path.name}.",
        suffix=".tmp",
        text=True,
    )
    temporary_path = Path(temporary_name)
    try:
        with os.fdopen(file_descriptor, "w", encoding="utf-8") as handle:
            handle.write(json.dumps(selection_set.to_dict(), ensure_ascii=False, indent=2) + "\n")
        os.replace(temporary_path, output_path)
    except BaseException:
        temporary_path.unlink(missing_ok=True)
        raise
    return output_path


def reinforce_resolved_clips_with_highlights(
    clips: tuple[ResolvedCandidateClip, ...],
    candidates: tuple[HighlightBridgeCandidate, ...],
    catalog: VideoCatalog,
    *,
    selections: HighlightReinforcementSelectionSet | None = None,
) -> tuple[ResolvedCandidateClip, ...]:
    """Narrow a matched clip's interval using one overlapping highlight window.

    Only narrows: the returned interval is always a subset of the original
    `[start_offset_s, end_offset_s]`, and is only replaced when it is
    strictly smaller. `asset_id`, `status`, and every other field besides
    `start_offset_s`/`end_offset_s`/`reason` are unchanged. Never touches an
    unmatched clip, evidence decisions, the automatic-confirmation policy, or
    the clock-offset human confirmation.

    Fails closed (returns the original clip unchanged) on every ambiguous or
    unsafe case: an unmatched clip, no overlapping candidate that lies fully
    inside the same catalog entry the clip was resolved against ("asset
    identity" — see module docstring), more than one such candidate with no
    unique, comparable priority among them (see `_select_unambiguous_candidate`),
    a resolved asset no longer present in `catalog`, or a resulting interval
    that is not strictly narrower than the original.

    ``selections`` optionally overrides the automatic priority for a clip
    whose event has an explicit `HighlightReinforcementSelection` — see the
    module docstring for exactly how it is validated and when it is ignored
    in favor of leaving the clip unchanged. Omitting it (the default)
    reproduces prior behaviour exactly.
    """
    entries_by_asset_id = {entry.asset_id: entry for entry in catalog.entries}
    return tuple(
        _reinforce_one_clip(clip, candidates, catalog, entries_by_asset_id, selections)
        for clip in clips
    )


def _select_unambiguous_candidate(
    valid_candidates: tuple[HighlightBridgeCandidate, ...],
) -> HighlightBridgeCandidate | None:
    """Pick the one candidate to reinforce with, or None if ambiguous.

    `HighlightBridgeCandidate.score` means something different for each
    `QualitySelectionMethod`, so candidates are never ranked against each
    other across methods. When every candidate shares the same method, rank
    is a stable, method-internal ordering; the candidate with the uniquely
    lowest rank wins. A mix of methods, or a tied lowest rank, has no safe
    unique answer and returns None.

    A single candidate is always unambiguous, independent of this rule.
    """
    if not valid_candidates:
        return None
    if len(valid_candidates) == 1:
        return valid_candidates[0]
    if len({candidate.method for candidate in valid_candidates}) != 1:
        return None
    ranked = sorted(valid_candidates, key=lambda candidate: candidate.rank)
    if ranked[0].rank == ranked[1].rank:
        return None
    return ranked[0]


def _select_candidate(
    event_id: str,
    valid_candidates: tuple[HighlightBridgeCandidate, ...],
    selections: HighlightReinforcementSelectionSet | None,
) -> HighlightBridgeCandidate | None:
    """Prefer an explicit, independently-valid selection; else pick automatically.

    A selection recorded for this event that does not match any
    already-safety-checked candidate (unknown, stale, wrong clip, or
    asset-mismatched) is not a reason to fall back to the automatic pick: it
    returns None so the caller leaves the clip unchanged, same as any other
    fail-closed case.
    """
    selected_candidate_id = selections.candidate_id_for(event_id) if selections else None
    if selected_candidate_id is not None:
        return next(
            (
                candidate
                for candidate in valid_candidates
                if candidate.candidate_id == selected_candidate_id
            ),
            None,
        )
    return _select_unambiguous_candidate(valid_candidates)


def _reinforce_one_clip(
    clip: ResolvedCandidateClip,
    candidates: tuple[HighlightBridgeCandidate, ...],
    catalog: VideoCatalog,
    entries_by_asset_id: dict[str, VideoCatalogEntry],
    selections: HighlightReinforcementSelectionSet | None,
) -> ResolvedCandidateClip:
    if clip.status is not VideoMatchStatus.MATCHED:
        return clip
    assert clip.asset_id is not None
    assert clip.start_offset_s is not None
    assert clip.end_offset_s is not None
    entry = entries_by_asset_id.get(clip.asset_id)
    if entry is None:
        # The clip's asset is not (or no longer) in this catalog: fail closed
        # rather than guess which entry it might correspond to.
        return clip

    asset_start = catalog.gps_start_time(entry)
    asset_end = asset_start + timedelta(seconds=entry.duration_s)
    clip_start_abs = asset_start + timedelta(seconds=clip.start_offset_s)
    clip_end_abs = asset_start + timedelta(seconds=clip.end_offset_s)

    overlapping = tuple(
        candidate
        for candidate in candidates
        if candidate.start_time < clip_end_abs and clip_start_abs < candidate.end_time
    )
    # Asset identity: a candidate's absolute window must lie fully inside the
    # same catalog entry the clip was resolved against. A candidate window is
    # never split across, or attributed to, a different asset. Candidates
    # that fail this are dropped before priority is considered, not treated
    # as a reason to fail closed by themselves — a real overlap can coexist
    # with an unrelated cross-asset one.
    valid = tuple(
        candidate
        for candidate in overlapping
        if asset_start <= candidate.start_time and candidate.end_time <= asset_end
    )
    if not valid:
        return clip

    candidate = _select_candidate(clip.event_id, valid, selections)
    if candidate is None:
        # No candidate, no unique automatic priority, or an explicit
        # selection that did not independently pass validation.
        return clip

    candidate_start_offset_s = (candidate.start_time - asset_start).total_seconds()
    candidate_end_offset_s = candidate_start_offset_s + candidate.duration_s

    new_start_offset_s = max(clip.start_offset_s, candidate_start_offset_s)
    new_end_offset_s = min(clip.end_offset_s, candidate_end_offset_s)
    if new_end_offset_s <= new_start_offset_s:
        # Absolute-time overlap does not guarantee a valid offset-space
        # intersection once both are clamped to the resolved clip; treat as
        # an invalid resulting interval and keep the original.
        return clip

    original_duration_s = clip.end_offset_s - clip.start_offset_s
    new_duration_s = new_end_offset_s - new_start_offset_s
    if new_duration_s >= original_duration_s:
        # Not actually narrower: nothing to reinforce.
        return clip

    return replace(
        clip,
        start_offset_s=new_start_offset_s,
        end_offset_s=new_end_offset_s,
        reason="ハイライト候補により候補区間を補強しました。",
    )


HIGHLIGHT_REINFORCEMENT_CONFLICT_SCHEMA_VERSION = "local-highlight-reinforcement-conflict-v1"


@dataclass(frozen=True)
class HighlightReinforcementConflict:
    """One candidate competing, unresolved, for one resolved clip's event.

    See the "Listing unresolved conflicts" section of the module docstring
    for exactly when this is produced. Carries only identifiers already
    opaque elsewhere in this module and the method/rank pair a future UI
    needs to explain the conflict — no location, path, asset name, video
    content, absolute time, offset, score, or credential.
    """

    event_id: str
    candidate_id: str
    method: QualitySelectionMethod
    rank: int

    def __post_init__(self) -> None:
        if not self.event_id or not self.candidate_id:
            raise ValueError("reinforcement conflict requires event_id and candidate_id")
        if self.rank <= 0:
            raise ValueError("reinforcement conflict rank must be positive")

    def to_dict(self) -> dict[str, object]:
        return {
            "event_id": self.event_id,
            "candidate_id": self.candidate_id,
            "method": self.method.value,
            "rank": self.rank,
        }


@dataclass(frozen=True)
class HighlightReinforcementConflictSet:
    """Every unresolved conflict, each candidate listed for at most one clip."""

    conflicts: tuple[HighlightReinforcementConflict, ...]

    def __post_init__(self) -> None:
        pairs = [(conflict.event_id, conflict.candidate_id) for conflict in self.conflicts]
        candidate_ids = [conflict.candidate_id for conflict in self.conflicts]
        if len(pairs) != len(set(pairs)):
            raise ValueError("reinforcement conflicts must not repeat an event/candidate pairing")
        if len(candidate_ids) != len(set(candidate_ids)):
            raise ValueError("reinforcement conflicts must not list the same candidate twice")

    def to_dict(self) -> dict[str, object]:
        return {
            "schema_version": HIGHLIGHT_REINFORCEMENT_CONFLICT_SCHEMA_VERSION,
            "conflicts": [conflict.to_dict() for conflict in self.conflicts],
        }


def _valid_narrowing_candidates(
    clip: ResolvedCandidateClip,
    candidates: tuple[HighlightBridgeCandidate, ...],
    catalog: VideoCatalog,
    entries_by_asset_id: dict[str, VideoCatalogEntry],
) -> tuple[HighlightBridgeCandidate, ...]:
    """Every candidate that would, on its own, safely narrow this clip.

    Applies the same three checks `_reinforce_one_clip` applies to whichever
    single candidate it ends up choosing — asset identity, absolute-time
    overlap, and a strictly narrower resulting interval — but to every
    candidate independently, not just the one that would eventually be
    selected. This is intentionally kept separate from `_reinforce_one_clip`
    rather than shared, so that listing conflicts can never change what that
    already-tested function actually does.
    """
    if clip.status is not VideoMatchStatus.MATCHED:
        return ()
    assert clip.asset_id is not None
    assert clip.start_offset_s is not None
    assert clip.end_offset_s is not None
    entry = entries_by_asset_id.get(clip.asset_id)
    if entry is None:
        return ()

    asset_start = catalog.gps_start_time(entry)
    asset_end = asset_start + timedelta(seconds=entry.duration_s)
    clip_start_abs = asset_start + timedelta(seconds=clip.start_offset_s)
    clip_end_abs = asset_start + timedelta(seconds=clip.end_offset_s)
    original_duration_s = clip.end_offset_s - clip.start_offset_s

    valid: list[HighlightBridgeCandidate] = []
    for candidate in candidates:
        if not (candidate.start_time < clip_end_abs and clip_start_abs < candidate.end_time):
            continue
        if not (asset_start <= candidate.start_time and candidate.end_time <= asset_end):
            continue
        candidate_start_offset_s = (candidate.start_time - asset_start).total_seconds()
        candidate_end_offset_s = candidate_start_offset_s + candidate.duration_s
        new_start_offset_s = max(clip.start_offset_s, candidate_start_offset_s)
        new_end_offset_s = min(clip.end_offset_s, candidate_end_offset_s)
        if new_end_offset_s <= new_start_offset_s:
            continue
        if new_end_offset_s - new_start_offset_s >= original_duration_s:
            continue
        valid.append(candidate)
    return tuple(valid)


def find_highlight_reinforcement_conflicts(
    clips: tuple[ResolvedCandidateClip, ...],
    candidates: tuple[HighlightBridgeCandidate, ...],
    catalog: VideoCatalog,
) -> HighlightReinforcementConflictSet:
    """List every clip whose reinforcement is still ambiguous.

    See the "Listing unresolved conflicts" section of the module docstring.
    A clip is only listed when at least two candidates independently pass
    asset identity, absolute-time overlap, and strict narrowing (see
    `_valid_narrowing_candidates`), and `_select_unambiguous_candidate`
    still cannot pick a unique winner among them (a mix of
    `QualitySelectionMethod` values, or a tied lowest rank). An unmatched
    clip, one whose asset is missing from `catalog`, a candidate that fails
    any of the three checks, and a clip that already resolves automatically,
    never appear here.

    Output is deterministically ordered by `(event_id, method, rank,
    candidate_id)`. Each resolved clip contributes conflict rows only for
    its own event_id; the same candidate cannot appear twice because
    `HighlightReinforcementConflictSet` itself rejects that.
    """
    entries_by_asset_id = {entry.asset_id: entry for entry in catalog.entries}
    conflicts: list[HighlightReinforcementConflict] = []
    for clip in clips:
        valid = _valid_narrowing_candidates(clip, candidates, catalog, entries_by_asset_id)
        if not valid:
            continue
        if _select_unambiguous_candidate(valid) is not None:
            continue
        for candidate in valid:
            conflicts.append(
                HighlightReinforcementConflict(
                    event_id=clip.event_id,
                    candidate_id=candidate.candidate_id,
                    method=candidate.method,
                    rank=candidate.rank,
                )
            )
    conflicts.sort(
        key=lambda conflict: (
            conflict.event_id,
            conflict.method.value,
            conflict.rank,
            conflict.candidate_id,
        )
    )
    return HighlightReinforcementConflictSet(tuple(conflicts))


def load_highlight_reinforcement_conflicts(path: Path) -> HighlightReinforcementConflictSet:
    """Load a conflict list, failing closed on anything unexpected.

    Rejects a symlinked or missing path, malformed JSON, an unsupported or
    missing schema version, any top-level or per-conflict field other than
    exactly what this contract defines, a non-string event_id/candidate_id,
    an unknown method value, a non-positive rank, a repeated event/candidate
    pairing, and a candidate listed under more than one event.
    """
    if path.is_symlink() or not path.is_file():
        raise ValueError("highlight reinforcement conflicts are unavailable")
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise ValueError("highlight reinforcement conflicts are unreadable") from error
    if not isinstance(payload, dict) or set(payload) != {"schema_version", "conflicts"}:
        raise ValueError("highlight reinforcement conflicts have an invalid schema")
    if payload["schema_version"] != HIGHLIGHT_REINFORCEMENT_CONFLICT_SCHEMA_VERSION:
        raise ValueError("unsupported highlight reinforcement conflict schema")
    raw_conflicts = payload["conflicts"]
    if not isinstance(raw_conflicts, list):
        raise ValueError("highlight reinforcement conflicts have an invalid schema")
    conflicts: list[HighlightReinforcementConflict] = []
    for item in raw_conflicts:
        if not isinstance(item, dict) or set(item) != {
            "event_id",
            "candidate_id",
            "method",
            "rank",
        }:
            raise ValueError("highlight reinforcement conflicts have an invalid schema")
        event_id, candidate_id, method, rank = (
            item["event_id"],
            item["candidate_id"],
            item["method"],
            item["rank"],
        )
        if not isinstance(event_id, str) or not isinstance(candidate_id, str):
            raise ValueError("highlight reinforcement conflicts have an invalid schema")
        if not isinstance(method, str):
            raise ValueError("highlight reinforcement conflicts have an invalid schema")
        if isinstance(rank, bool) or not isinstance(rank, int):
            raise ValueError("highlight reinforcement conflicts have an invalid schema")
        conflicts.append(
            HighlightReinforcementConflict(
                event_id=event_id,
                candidate_id=candidate_id,
                method=QualitySelectionMethod(method),
                rank=rank,
            )
        )
    return HighlightReinforcementConflictSet(tuple(conflicts))


def write_highlight_reinforcement_conflicts(
    output_path: Path,
    conflict_set: HighlightReinforcementConflictSet,
    *,
    overwrite: bool = False,
) -> Path:
    """Persist a conflict list atomically to a caller-chosen private path.

    Defaults to not overwriting, the same as
    `write_highlight_reinforcement_selections`: a private sidecar a human
    may be actively working from should not be silently replaced by a rerun.
    """
    if output_path.is_symlink():
        raise ValueError("highlight reinforcement conflicts path must not be a symlink")
    if output_path.exists() and not overwrite:
        raise FileExistsError(
            "highlight reinforcement conflicts already exist; choose a new path or pass "
            "overwrite=True"
        )
    output_path.parent.mkdir(parents=True, exist_ok=True)
    file_descriptor, temporary_name = mkstemp(
        dir=output_path.parent,
        prefix=f".{output_path.name}.",
        suffix=".tmp",
        text=True,
    )
    temporary_path = Path(temporary_name)
    try:
        with os.fdopen(file_descriptor, "w", encoding="utf-8") as handle:
            handle.write(json.dumps(conflict_set.to_dict(), ensure_ascii=False, indent=2) + "\n")
        os.replace(temporary_path, output_path)
    except BaseException:
        temporary_path.unlink(missing_ok=True)
        raise
    return output_path
