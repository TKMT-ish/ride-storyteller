"""Scout: bridge between GPS/video analysis and the Director.

This module converts existing domain objects into ``UniversalEvent``, the
stable contract passed to the Director.  It owns no evidence state — evidence
is confirmed upstream (video analysis or human review) and expressed through
``CandidateClip.evidence_status`` before this adapter is called.

Raw latitude/longitude values are intentionally excluded from
``UniversalEvent``.  Only semantic location context (place name, POI type,
road context, elevation) is included so that the Director can understand the
meaning of a location without receiving private route coordinates.

Actual file names, paths, and URIs are also excluded.  Source identity is
expressed through the opaque catalog ``asset_id`` only.

Video-evidence gate — two lines of defence
------------------------------------------
Unconfirmed clips are prevented from reaching an FFmpeg render plan by two
independent, fail-closed checks that each operate at a different layer:

**First line of defence — Director input filter (this module)**
    Only ``UniversalEvent`` instances where ``evidence_confirmed=True`` are
    passed to the Director.  ``evidence_confirmed`` is ``True`` only when
    *both* conditions hold simultaneously:

    * ``CandidateClip.evidence_status is CandidateEvidenceStatus.CONFIRMED``
    * ``ResolvedCandidateClip.status is VideoMatchStatus.MATCHED``

    Any event that does not satisfy both conditions has
    ``evidence_confirmed=False`` and is excluded before the Director ever
    sees it.  The Director therefore operates exclusively on events that
    have passed human or automated review *and* have a physical asset
    match on record.

**Second line of defence — ``build_ffmpeg_render_plan`` (app/edit/render_plan.py)**
    The existing render-plan builder is fail-closed on a caller-supplied
    allow-list ``visual_evidence_confirmed_event_ids``.  If any clip in the
    render plan is absent from that allow-list the function returns::

        FfmpegRenderPlan(
            status=RenderPlanStatus.NEEDS_HUMAN_REVIEW,
            command=None,
            ...
        )

    The FFmpeg command string is never produced.  This gate is not modified
    by the Scout/Director/Editor pipeline; it is inherited unchanged and
    remains effective even if an unconfirmed event were to reach the
    ``ScriptExecutor`` due to a future integration error.

Together the two gates ensure that a clip missing ``evidence_confirmed=True``
cannot reach FFmpeg rendering regardless of which layer first encounters it.

Design contracts enforced by ``to_universal_event``
----------------------------------------------------
1. ``candidate_clip.event_id`` must equal ``gps_event.event_id`` when a clip
   is supplied.  Mismatches raise ``ValueError``.

2. ``resolved_clip.event_id`` must equal ``gps_event.event_id`` when a
   resolved clip is supplied.  Mismatches raise ``ValueError``.
   When both ``candidate_clip`` and ``resolved_clip`` are supplied, all three
   ``event_id`` values must agree.

3. Source identity (``source_asset_id``, ``source_start_sec``,
   ``source_end_sec``) comes exclusively from a ``MATCHED``
   ``ResolvedCandidateClip``.  A NOT_FOUND clip is never a valid source.
   ``GpsEvent.video_query`` offsets are editorial *requests*, not resolved
   source intervals; they are exposed as ``requested_start_sec`` /
   ``requested_end_sec``.

4. ``scored_window`` requires both ``candidate_clip`` and ``resolved_clip``.
   The window's ``asset_id`` must match ``resolved_clip.asset_id``, and the
   window interval ``[start_offset_s, start_offset_s + duration_s]`` must be
   fully contained within ``[resolved_clip.start_offset_s,
   resolved_clip.end_offset_s]`` (within ``_WINDOW_CONTAINMENT_TOLERANCE_S``).
   When accepted, the window interval replaces the resolved clip interval as
   the source interval in ``UniversalEvent`` because the window is the
   Director's actual selection target.

5. ``evidence_confirmed=True`` implies ``evidence.video=True``.
   ``evidence_confirmed`` can only be ``True`` when ``candidate_clip`` is
   ``CONFIRMED`` *and* ``resolved_clip`` is ``MATCHED``.

6. Any visual score (``visual_score``, ``scenic_score``, ``ranking_score``)
   implies ``evidence.video=True``.

7. The three source fields (``source_asset_id``, ``source_start_sec``,
   ``source_end_sec``) are all-or-nothing: either all ``None`` (unresolved)
   or all non-``None`` (resolved).

8. ``ranking_score`` carries ``ScoredHighlightWindow.balanced_score``,
   a composite ranking value — not an evidence-confidence measure.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

from app.contracts import GpsEvent
from app.edit.candidate_planner import CandidateClip, CandidateEvidenceStatus
from app.video.catalog import ResolvedCandidateClip, VideoMatchStatus

if TYPE_CHECKING:
    from app.video.highlight_quality import ScoredHighlightWindow

# Tolerance for floating-point boundary checks on window containment.
# This covers only floating-point rounding; it is not a large correction.
_WINDOW_CONTAINMENT_TOLERANCE_S: float = 1e-9


@dataclass(frozen=True)
class UniversalEventEvidence:
    """Which evidence signals are present for this event."""

    gps: bool
    video: bool
    map: bool = False
    poi: bool = False
    elevation: bool = False


@dataclass(frozen=True)
class UniversalEventLocationContext:
    """Semantic location context sent to the Director.

    Raw latitude/longitude are deliberately excluded.  Only named, descriptive
    attributes that help the Director understand the geographic meaning of a
    location are included here.
    """

    place_name: str | None = None
    poi_type: str | None = None
    road_context: str | None = None
    elevation_m: float | None = None


@dataclass(frozen=True)
class UniversalEvent:
    """Story-ready event that the Director uses to compose a script.

    Source identity
    ~~~~~~~~~~~~~~~
    ``source_asset_id``, ``source_start_sec``, and ``source_end_sec`` are
    derived from a ``MATCHED`` ``ResolvedCandidateClip`` (optionally refined
    to the ``ScoredHighlightWindow`` interval when one is accepted).  All
    three are ``None`` when no resolved source exists.

    Requested interval
    ~~~~~~~~~~~~~~~~~~
    ``requested_start_sec`` and ``requested_end_sec`` come from
    ``GpsEvent.video_query`` and represent the *editorial request*, not the
    resolved source.

    Scores
    ~~~~~~
    ``visual_score`` and ``scenic_score`` are ``None`` when the
    highlight-analysis pass has not been run.  ``ranking_score`` is
    ``ScoredHighlightWindow.balanced_score`` — a composite ranking value,
    not an evidence-confidence measure.

    Invariants enforced by ``__post_init__``
    ~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~
    * ``evidence_confirmed=True`` → ``evidence.video=True``
    * ``evidence_confirmed=True`` → source three fields all non-``None``
    * Any score present → ``evidence.video=True``
    * Any score present → source three fields all non-``None``
    * Source fields are all-or-nothing (all ``None`` or all non-``None``)
    * When resolved: ``source_asset_id`` non-empty, ``source_start_sec >= 0``,
      ``source_end_sec > source_start_sec``
    * ``requested_start_sec >= 0`` and ``requested_end_sec >= requested_start_sec``
    """

    event_id: str
    event_type: str
    sub_category: str | None
    # Resolved source identity (from ResolvedCandidateClip / ScoredHighlightWindow)
    source_asset_id: str | None
    source_start_sec: float | None
    source_end_sec: float | None
    # Editorial request (from GpsEvent.video_query)
    requested_start_sec: float
    requested_end_sec: float
    intensity: float
    visual_score: float | None
    scenic_score: float | None
    ranking_score: float | None
    location_context: UniversalEventLocationContext
    evidence: UniversalEventEvidence
    evidence_confirmed: bool

    def __post_init__(self) -> None:
        if not self.event_id or not self.event_type:
            raise ValueError("event_id and event_type are required")
        # Requested interval validation
        if self.requested_start_sec < 0:
            raise ValueError("requested_start_sec must be non-negative")
        if self.requested_end_sec < self.requested_start_sec:
            raise ValueError("requested_end_sec must not be before requested_start_sec")
        if not 0.0 <= self.intensity <= 1.0:
            raise ValueError("intensity must be between 0.0 and 1.0")
        for name, value in (
            ("visual_score", self.visual_score),
            ("scenic_score", self.scenic_score),
            ("ranking_score", self.ranking_score),
        ):
            if value is not None and not 0.0 <= value <= 1.0:
                raise ValueError(f"{name} must be between 0.0 and 1.0")
        # Source fields are all-or-nothing
        source_fields = (self.source_asset_id, self.source_start_sec, self.source_end_sec)
        none_count = sum(v is None for v in source_fields)
        if none_count not in (0, 3):
            raise ValueError(
                "source_asset_id, source_start_sec, and source_end_sec "
                "must all be None (unresolved) or all non-None (resolved)"
            )
        # When resolved: asset must be non-empty, offsets must be valid
        if self.source_asset_id is not None:
            if not self.source_asset_id.strip():
                raise ValueError("source_asset_id must be a non-empty, non-whitespace string")
            assert self.source_start_sec is not None and self.source_end_sec is not None
            if self.source_start_sec < 0:
                raise ValueError("source_start_sec must be non-negative")
            if self.source_end_sec <= self.source_start_sec:
                raise ValueError("source_end_sec must be after source_start_sec")
        # evidence_confirmed=True requires evidence.video=True and resolved source
        if self.evidence_confirmed and not self.evidence.video:
            raise ValueError(
                "evidence_confirmed=True requires evidence.video=True"
            )
        if self.evidence_confirmed and self.source_asset_id is None:
            raise ValueError(
                "evidence_confirmed=True requires a resolved source "
                "(source_asset_id, source_start_sec, source_end_sec must all be set)"
            )
        # Any visual score requires evidence.video=True and resolved source
        has_score = any(
            v is not None for v in (self.visual_score, self.scenic_score, self.ranking_score)
        )
        if has_score and not self.evidence.video:
            raise ValueError(
                "visual_score, scenic_score, or ranking_score requires evidence.video=True"
            )
        if has_score and self.source_asset_id is None:
            raise ValueError(
                "visual_score, scenic_score, or ranking_score requires a resolved source "
                "(source_asset_id, source_start_sec, source_end_sec must all be set)"
            )


def to_universal_event(
    gps_event: GpsEvent,
    candidate_clip: CandidateClip | None = None,
    resolved_clip: ResolvedCandidateClip | None = None,
    scored_window: ScoredHighlightWindow | None = None,
    *,
    location_context: UniversalEventLocationContext | None = None,
    sub_category: str | None = None,
) -> UniversalEvent:
    """Convert a ``GpsEvent`` (and optional richer sources) to a ``UniversalEvent``.

    Parameters
    ----------
    gps_event:
        The canonical GPS event produced by ``extract_events``.
    candidate_clip:
        The ``CandidateClip`` for *this* event.  Carries ``evidence_status``
        only; it is **not** a resolved source.  Must satisfy
        ``candidate_clip.event_id == gps_event.event_id``.
    resolved_clip:
        The ``ResolvedCandidateClip`` that maps this event to a physical asset.
        Must be ``MATCHED`` to supply source identity.  Must satisfy
        ``resolved_clip.event_id == gps_event.event_id``.
    scored_window:
        Optional highlight-quality window.  Requires both ``candidate_clip``
        and a ``MATCHED`` ``resolved_clip``.  The window's ``asset_id`` must
        match ``resolved_clip.asset_id``, and the window interval must be
        fully contained within the resolved clip interval.  When accepted,
        the window interval becomes the source interval in ``UniversalEvent``.
    location_context:
        Caller-supplied semantic location context (no raw coordinates).
    sub_category:
        Optional fine-grained sub-category (e.g. ``"mountain_pass"``).

    Raises
    ------
    ValueError
        On any ID mismatch, unmatched resolved clip used as source,
        scored_window/resolved_clip missing or mismatched, out-of-range
        window interval, or invalid field values.
    """
    # ------------------------------------------------------------------
    # 1. event_id consistency across all supplied objects
    # ------------------------------------------------------------------
    if candidate_clip is not None and candidate_clip.event_id != gps_event.event_id:
        raise ValueError(
            f"candidate_clip.event_id {candidate_clip.event_id!r} does not match "
            f"gps_event.event_id {gps_event.event_id!r}"
        )
    if resolved_clip is not None and resolved_clip.event_id != gps_event.event_id:
        raise ValueError(
            f"resolved_clip.event_id {resolved_clip.event_id!r} does not match "
            f"gps_event.event_id {gps_event.event_id!r}"
        )
    if (
        candidate_clip is not None
        and resolved_clip is not None
        and candidate_clip.chapter_id != resolved_clip.chapter_id
    ):
        raise ValueError(
            f"candidate_clip.chapter_id {candidate_clip.chapter_id!r} does not match "
            f"resolved_clip.chapter_id {resolved_clip.chapter_id!r}"
        )

    # ------------------------------------------------------------------
    # 2. scored_window prerequisite checks
    # ------------------------------------------------------------------
    if scored_window is not None:
        if candidate_clip is None:
            raise ValueError(
                "scored_window requires candidate_clip; "
                "supplying a window without a resolved candidate_clip "
                "risks attaching visual metrics from an unrelated asset"
            )
        if resolved_clip is None:
            raise ValueError(
                "scored_window requires resolved_clip; "
                "supplying a window without a ResolvedCandidateClip "
                "makes asset association unverifiable"
            )

    # ------------------------------------------------------------------
    # 3. source identity from ResolvedCandidateClip
    # ------------------------------------------------------------------
    source_asset_id: str | None = None
    source_start_sec: float | None = None
    source_end_sec: float | None = None

    if resolved_clip is not None:
        if resolved_clip.status is not VideoMatchStatus.MATCHED:
            raise ValueError(
                f"resolved_clip for {resolved_clip.event_id!r} has status "
                f"{resolved_clip.status.value!r}; only MATCHED clips provide source identity"
            )
        # MATCHED guarantees these are non-None (enforced by ResolvedCandidateClip.__post_init__)
        source_asset_id = resolved_clip.asset_id
        source_start_sec = resolved_clip.start_offset_s
        source_end_sec = resolved_clip.end_offset_s

    # ------------------------------------------------------------------
    # 4. ScoredHighlightWindow asset and interval verification
    # ------------------------------------------------------------------
    visual_score: float | None = None
    scenic_score: float | None = None
    ranking_score: float | None = None

    if scored_window is not None:
        # resolved_clip is guaranteed non-None here (checked above)
        assert resolved_clip is not None
        window = scored_window.evidence.window
        window_asset_id = window.asset_id
        if window_asset_id != resolved_clip.asset_id:
            raise ValueError(
                f"scored_window asset_id {window_asset_id!r} does not match "
                f"resolved_clip asset_id {resolved_clip.asset_id!r}"
            )
        window_start = window.start_offset_s
        window_end = window.start_offset_s + window.duration_s
        resolved_start = resolved_clip.start_offset_s
        resolved_end = resolved_clip.end_offset_s
        assert resolved_start is not None and resolved_end is not None
        tol = _WINDOW_CONTAINMENT_TOLERANCE_S
        if window_start < resolved_start - tol:
            raise ValueError(
                f"scored_window starts at {window_start}s which is before "
                f"resolved_clip start {resolved_start}s"
            )
        if window_end > resolved_end + tol:
            raise ValueError(
                f"scored_window ends at {window_end}s which is after "
                f"resolved_clip end {resolved_end}s"
            )
        # Window interval is the Director's actual selection target
        source_start_sec = window_start
        source_end_sec = window_end
        visual_score = scored_window.quality_score
        scenic_score = scored_window.scenic_score
        ranking_score = scored_window.balanced_score

    # ------------------------------------------------------------------
    # 5. evidence flags
    # ------------------------------------------------------------------
    evidence_confirmed = (
        candidate_clip is not None
        and candidate_clip.evidence_status is CandidateEvidenceStatus.CONFIRMED
        and resolved_clip is not None
        and resolved_clip.status is VideoMatchStatus.MATCHED
    )
    has_video_evidence = evidence_confirmed or (
        candidate_clip is not None
        and candidate_clip.evidence_status is CandidateEvidenceStatus.REJECTED
    )
    # A verified scored_window always implies video signal was present
    if scored_window is not None:
        has_video_evidence = True

    # ------------------------------------------------------------------
    # 6. requested interval from GpsEvent.video_query
    # ------------------------------------------------------------------
    query = gps_event.video_query

    return UniversalEvent(
        event_id=gps_event.event_id,
        event_type=gps_event.event_type,
        sub_category=sub_category,
        source_asset_id=source_asset_id,
        source_start_sec=source_start_sec,
        source_end_sec=source_end_sec,
        requested_start_sec=query.clip_start_offset_s,
        requested_end_sec=query.clip_end_offset_s,
        intensity=gps_event.importance_hint,
        visual_score=visual_score,
        scenic_score=scenic_score,
        ranking_score=ranking_score,
        location_context=location_context or UniversalEventLocationContext(),
        evidence=UniversalEventEvidence(
            gps=True,
            video=has_video_evidence,
            elevation=(
                location_context is not None and location_context.elevation_m is not None
            ),
        ),
        evidence_confirmed=evidence_confirmed,
    )
