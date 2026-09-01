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
Only a highlight candidate whose absolute time window does not overlap any
existing `GpsEvent` is promoted to a new event. A candidate that does overlap
an existing event is left alone; using it to *reinforce* that event's
resolved clip interval is a separate, not-yet-implemented step (design doc
§3.1). This module still has no caller in `app.local_pipeline` or any CLI;
wiring it in is a separate decision (design doc §7-2).
"""

from __future__ import annotations

import hashlib
import json
import os
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path
from tempfile import mkstemp

from app.contracts import GpsEvent, Location, VideoQuery

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
                interest_lanes=tuple(
                    InterestLane(lane) for lane in item["interest_lanes"]
                ),
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
            "highlight bridge candidates already exist; choose a new path or pass "
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
