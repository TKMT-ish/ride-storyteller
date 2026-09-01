"""Bridge approved highlight candidates into the GPS-event story pipeline.

See docs/highlight-story-bridge-design-ja.md for the full design. In short:
GPS-derived events and video-derived highlight candidates currently reach
confirmed evidence through two separate contracts (`app.video.review` and
`app.video.highlight_review`). This module converts an *approved* highlight
candidate (`HighlightReviewStatus.APPROVED`) into a `GpsEvent` so it can join
the same Story Plan / candidate-edit / evidence-review pipeline as any
GPS-derived event, without changing either existing contract.

Scope of this increment
------------------------
Only a highlight candidate whose absolute time window does not overlap any
existing `GpsEvent` is promoted to a new event. A candidate that does overlap
an existing event is left alone; using it to *reinforce* that event's
resolved clip interval is a separate, not-yet-implemented step (design doc
§3.1). This module also does not read or write any file: it operates on
already-computed `QualitySelection` and `HighlightReviewResult` in memory
from one `run_local_highlight_research` call, because `QualitySelection`
(Vision frames, GPMF summaries, raw window features) has no on-disk
serialization today. Wiring this into `app.local_pipeline`'s default flow
would require designing that persistence first; this module intentionally
does not decide that.

No source path, file name, or camera timestamp is placed in the resulting
`GpsEvent`. The event's `evidence` field carries only the interest-lane
values already used by the private review contracts (e.g. "strong_turn"),
not any private identifier.
"""

from __future__ import annotations

import hashlib
from datetime import UTC, datetime, timedelta

from app.contracts import GpsEvent, Location, VideoQuery

from .highlight_quality import QualitySelection, QualitySelectionMethod
from .highlight_review import HighlightReviewResult

HIGHLIGHT_EVENT_TYPE = "visual_highlight"


class HighlightStoryBridgeError(ValueError):
    """Raised when a highlight candidate cannot be promoted to a GpsEvent."""


def _absolute_window(selection: QualitySelection) -> tuple[datetime, datetime]:
    """Return the window's absolute [start, end) GPS-clock time.

    `WindowFeatures.timeline_s` is already an absolute GPS-clock Unix
    timestamp (see `highlight_discovery._features_for_source`), not a
    video-relative offset.
    """
    window = selection.scored.evidence.window
    start = datetime.fromtimestamp(window.timeline_s, tz=UTC)
    return start, start + timedelta(seconds=window.duration_s)


def _location_for(selection: QualitySelection) -> Location | None:
    window = selection.scored.evidence.window
    if window.latitude is None or window.longitude is None:
        return None
    return Location(window.latitude, window.longitude)


def _highlight_event_id(selection: QualitySelection) -> str:
    """Derive a stable event ID from window identity alone (not method/rank).

    The same physical window is often chosen by more than one selection
    method; deriving the ID from window identity lets those duplicates
    collapse to one event instead of producing near-identical events.
    """
    window = selection.scored.evidence.window
    material = "\0".join(
        (window.asset_id, f"{window.start_offset_s:.6f}", f"{window.duration_s:.6f}")
    )
    return f"highlight-event-{hashlib.sha256(material.encode('utf-8')).hexdigest()[:16]}"


def overlaps_existing_event(
    selection: QualitySelection, existing_events: tuple[GpsEvent, ...]
) -> bool:
    """Return True if the candidate's absolute time window overlaps any event."""
    start, end = _absolute_window(selection)
    return any(start < event.end_time and event.start_time < end for event in existing_events)


def build_highlight_gps_event(selection: QualitySelection) -> GpsEvent:
    """Synthesize one video-originated GpsEvent from an approved candidate.

    Raises `HighlightStoryBridgeError` if the candidate has no recorded GPS
    location (only possible for a window whose route coverage was too sparse
    for `highlight_discovery._gps_features` to report a midpoint location).
    """
    location = _location_for(selection)
    if location is None:
        raise HighlightStoryBridgeError("highlight candidate has no recorded GPS location")
    start, end = _absolute_window(selection)
    window = selection.scored.evidence.window
    evidence = tuple(dict.fromkeys(lane.value for lane in selection.scored.interest_lanes))
    if not evidence:
        raise HighlightStoryBridgeError("highlight candidate has no interest lane evidence")
    importance_hint = max(0.0, min(1.0, selection.scored.score_for(selection.method)))
    return GpsEvent(
        event_id=_highlight_event_id(selection),
        event_type=HIGHLIGHT_EVENT_TYPE,
        start_time=start,
        end_time=end,
        location=location,
        importance_hint=importance_hint,
        evidence=evidence,
        video_query=VideoQuery(
            asset_name_hint=HIGHLIGHT_EVENT_TYPE,
            clip_start_offset_s=0.0,
            clip_end_offset_s=window.duration_s,
        ),
    )


def build_highlight_gps_events(
    selections: dict[QualitySelectionMethod, tuple[QualitySelection, ...]],
    review_result: HighlightReviewResult,
    existing_events: tuple[GpsEvent, ...],
) -> tuple[GpsEvent, ...]:
    """Promote every approved, non-overlapping highlight candidate to a GpsEvent.

    A manual rejection recorded in `review_result` always wins: only
    candidates in `review_result.approved_candidate_ids` are considered.
    Candidates whose window overlaps an existing GPS event are skipped (see
    module docstring). The same physical window selected by more than one
    method collapses to a single event.
    """
    from .highlight_review import highlight_review_candidate_id

    approved_ids = set(review_result.approved_candidate_ids)
    events_by_id: dict[str, GpsEvent] = {}
    for method in QualitySelectionMethod:
        for selection in selections.get(method, ()):
            if highlight_review_candidate_id(selection) not in approved_ids:
                continue
            if overlaps_existing_event(selection, existing_events):
                continue
            event = build_highlight_gps_event(selection)
            events_by_id.setdefault(event.event_id, event)
    return tuple(
        sorted(events_by_id.values(), key=lambda event: (event.start_time, event.event_id))
    )
