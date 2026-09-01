"""Decide and persist structured feedback for private highlight-review candidates.

As of 2026-09-01, the only required human confirmation in the local pipeline is
the camera-to-GPS clock offset (see `local_catalog.clock_offset_confirmed`).
`auto_decide_highlight_review` therefore approves every candidate that reached
this module automatically, using the interest lane(s) that already qualified it
under the deterministic hard gate. `find_highlight_review_borderline_candidates`
flags the weakest automatic decisions in a separate, non-blocking log so a human
can optionally revisit them later; nothing waits on that review. The lower-level
manual functions (`build_highlight_review_template`,
`update_highlight_review_decision`) remain available for that optional
correction and for tests.

This contract stores only opaque candidate IDs, selection method/rank, and fixed
reason codes. It intentionally excludes source paths, file names, timestamps,
coordinates, frames, and free-form notes so the feedback can be used for local
threshold evaluation without copying private-media identifiers into text fields.
"""

from __future__ import annotations

import hashlib
import json
import os
from collections import Counter
from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path
from tempfile import mkstemp

from .highlight_quality import (
    MINIMUM_CENTER_GYRO_SUSTAINED_RAD_S,
    MINIMUM_GYRO_SUSTAINED_RAD_S,
    MINIMUM_ROAD_CONTEXT_RATIO,
    InterestLane,
    QualitySelection,
    QualitySelectionMethod,
)

HIGHLIGHT_REVIEW_SCHEMA_VERSION = "local-highlight-review-v1"
HIGHLIGHT_REVIEW_BORDERLINE_LOG_SCHEMA_VERSION = "local-highlight-review-borderline-v1"

# The automatic decision requires exactly one human confirmation upstream (the
# camera-to-GPS clock offset). A candidate that reaches this module already
# passed the deterministic hard gate, so it is approved automatically using the
# interest lane(s) that qualified it. Borderline candidates are not blocked;
# they are recorded in a private, non-blocking log for optional later review.
DEFAULT_BORDERLINE_SCORE_QUANTILE = 0.1
DEFAULT_BORDERLINE_GATE_MARGIN_RATIO = 1.2


class HighlightReviewStatus(StrEnum):
    AWAITING = "awaiting"
    APPROVED = "approved"
    REJECTED = "rejected"


class HighlightReviewReason(StrEnum):
    CLEAR_TURN = "clear_turn"
    TEMPORAL_EVENT = "temporal_event"
    SCENIC_CONTEXT = "scenic_context"
    STORY_USEFUL = "story_useful"
    TOO_STRAIGHT = "too_straight"
    STOPPED_OR_SLOW = "stopped_or_slow"
    LOW_VISUAL_CHANGE = "low_visual_change"
    POOR_ROAD_CONTEXT = "poor_road_context"
    DUPLICATE = "duplicate"
    OTHER = "other"


_APPROVAL_REASONS = frozenset(
    {
        HighlightReviewReason.CLEAR_TURN,
        HighlightReviewReason.TEMPORAL_EVENT,
        HighlightReviewReason.SCENIC_CONTEXT,
        HighlightReviewReason.STORY_USEFUL,
    }
)
# Only lanes an automatic decision may cite as approval evidence. A candidate
# always carries at least one of these because it could not have passed the
# complete evidence gate otherwise (see highlight_quality.passes_complete_evidence_gate).
_LANE_APPROVAL_REASONS: dict[InterestLane, HighlightReviewReason] = {
    InterestLane.STRONG_TURN: HighlightReviewReason.CLEAR_TURN,
    InterestLane.VISUAL_EVENT: HighlightReviewReason.TEMPORAL_EVENT,
}

_REJECTION_REASONS = frozenset(
    {
        HighlightReviewReason.TOO_STRAIGHT,
        HighlightReviewReason.STOPPED_OR_SLOW,
        HighlightReviewReason.LOW_VISUAL_CHANGE,
        HighlightReviewReason.POOR_ROAD_CONTEXT,
        HighlightReviewReason.DUPLICATE,
        HighlightReviewReason.OTHER,
    }
)


@dataclass(frozen=True)
class HighlightReviewDecision:
    candidate_id: str
    method: QualitySelectionMethod
    rank: int
    status: HighlightReviewStatus
    reasons: tuple[HighlightReviewReason, ...] = ()

    def __post_init__(self) -> None:
        if not self.candidate_id or self.rank <= 0:
            raise ValueError("highlight review candidate ID and positive rank are required")
        if len(self.reasons) != len(set(self.reasons)):
            raise ValueError("highlight review reason codes must be unique")
        if self.status is HighlightReviewStatus.AWAITING:
            if self.reasons:
                raise ValueError("awaiting highlight review must not include reasons")
            return
        allowed = (
            _APPROVAL_REASONS
            if self.status is HighlightReviewStatus.APPROVED
            else _REJECTION_REASONS
        )
        if not self.reasons or not set(self.reasons) <= allowed:
            raise ValueError("highlight review reasons do not match the decision status")

    def to_dict(self) -> dict[str, object]:
        return {
            "candidate_id": self.candidate_id,
            "method": self.method.value,
            "rank": self.rank,
            "status": self.status.value,
            "reasons": [reason.value for reason in self.reasons],
        }


@dataclass(frozen=True)
class HighlightReview:
    decisions: tuple[HighlightReviewDecision, ...]

    def __post_init__(self) -> None:
        candidate_ids = [decision.candidate_id for decision in self.decisions]
        placement = [(decision.method, decision.rank) for decision in self.decisions]
        if len(candidate_ids) != len(set(candidate_ids)) or len(placement) != len(set(placement)):
            raise ValueError("highlight review decisions must identify unique candidates")

    def to_dict(self) -> dict[str, object]:
        return {
            "schema_version": HIGHLIGHT_REVIEW_SCHEMA_VERSION,
            "decisions": [decision.to_dict() for decision in self.decisions],
        }


@dataclass(frozen=True)
class HighlightReviewResult:
    approved_candidate_ids: tuple[str, ...]
    awaiting_candidate_ids: tuple[str, ...]
    rejected_candidate_ids: tuple[str, ...]
    reason_counts: dict[HighlightReviewReason, int]

    @property
    def is_complete(self) -> bool:
        return not self.awaiting_candidate_ids

    def to_dict(self) -> dict[str, object]:
        return {
            "is_complete": self.is_complete,
            "approved_candidate_ids": list(self.approved_candidate_ids),
            "awaiting_candidate_ids": list(self.awaiting_candidate_ids),
            "rejected_candidate_ids": list(self.rejected_candidate_ids),
            "reason_counts": {
                reason.value: self.reason_counts.get(reason, 0) for reason in HighlightReviewReason
            },
        }


class HighlightReviewBorderlineReason(StrEnum):
    """Why an auto-decided candidate was flagged for optional later review."""

    LOW_SCORE_MARGIN = "low_score_margin"
    NEAR_GATE_THRESHOLD = "near_gate_threshold"


@dataclass(frozen=True)
class HighlightReviewBorderlineEntry:
    """One non-blocking flag on an automatically approved candidate.

    Carries the same opaque identity as `HighlightReviewDecision` and no
    additional private detail; it exists only so a human can find and
    optionally revisit the weakest automatic decisions later.
    """

    candidate_id: str
    method: QualitySelectionMethod
    rank: int
    reasons: tuple[HighlightReviewBorderlineReason, ...]

    def __post_init__(self) -> None:
        if not self.candidate_id or self.rank <= 0:
            raise ValueError("borderline entry candidate ID and positive rank are required")
        if not self.reasons or len(self.reasons) != len(set(self.reasons)):
            raise ValueError("borderline entry requires unique, non-empty reasons")

    def to_dict(self) -> dict[str, object]:
        return {
            "candidate_id": self.candidate_id,
            "method": self.method.value,
            "rank": self.rank,
            "reasons": [reason.value for reason in self.reasons],
        }


@dataclass(frozen=True)
class HighlightReviewBorderlineLog:
    """Private, non-blocking record of automatically-decided borderline candidates."""

    entries: tuple[HighlightReviewBorderlineEntry, ...]

    def to_dict(self) -> dict[str, object]:
        return {
            "schema_version": HIGHLIGHT_REVIEW_BORDERLINE_LOG_SCHEMA_VERSION,
            "entries": [entry.to_dict() for entry in self.entries],
        }


def highlight_review_candidate_id(selection: QualitySelection) -> str:
    """Create a stable opaque ID from private selection identity without exporting it."""
    window = selection.scored.evidence.window
    material = "\0".join(
        (
            selection.method.value,
            str(selection.rank),
            window.asset_id,
            f"{window.start_offset_s:.6f}",
            f"{window.duration_s:.6f}",
        )
    )
    return f"highlight-{hashlib.sha256(material.encode('utf-8')).hexdigest()[:16]}"


def build_highlight_review_template(
    selections: dict[QualitySelectionMethod, tuple[QualitySelection, ...]],
) -> HighlightReview:
    """Create one awaiting decision for every current private review clip."""
    decisions: list[HighlightReviewDecision] = []
    for method in QualitySelectionMethod:
        for selection in selections.get(method, ()):
            if selection.method is not method:
                raise ValueError("highlight selection method does not match its collection")
            decisions.append(
                HighlightReviewDecision(
                    candidate_id=highlight_review_candidate_id(selection),
                    method=method,
                    rank=selection.rank,
                    status=HighlightReviewStatus.AWAITING,
                )
            )
    return HighlightReview(tuple(decisions))


def _approval_reasons_for(selection: QualitySelection) -> tuple[HighlightReviewReason, ...]:
    """Map the interest lane(s) that qualified a candidate to approval reasons.

    A candidate reaching this function already passed
    `highlight_quality.passes_complete_evidence_gate`, which requires at least
    one interest lane, so this always yields a non-empty, contract-valid tuple.
    """
    reasons = tuple(
        dict.fromkeys(
            _LANE_APPROVAL_REASONS[lane]
            for lane in selection.scored.interest_lanes
            if lane in _LANE_APPROVAL_REASONS
        )
    )
    if not reasons:
        raise ValueError("automatic approval requires at least one recognized interest lane")
    return reasons


def auto_decide_highlight_review(
    selections: dict[QualitySelectionMethod, tuple[QualitySelection, ...]],
) -> HighlightReview:
    """Approve every current candidate automatically from its interest lane(s).

    This is the sole decision step once the one required human confirmation
    (camera-to-GPS clock offset, `local_catalog.clock_offset_confirmed`) is in
    place; no per-candidate human approval is requested. Weak candidates are not
    rejected here — `find_highlight_review_borderline_candidates` flags them in
    a separate, non-blocking log instead of gating this decision.
    """
    decisions: list[HighlightReviewDecision] = []
    for method in QualitySelectionMethod:
        for selection in selections.get(method, ()):
            if selection.method is not method:
                raise ValueError("highlight selection method does not match its collection")
            decisions.append(
                HighlightReviewDecision(
                    candidate_id=highlight_review_candidate_id(selection),
                    method=method,
                    rank=selection.rank,
                    status=HighlightReviewStatus.APPROVED,
                    reasons=_approval_reasons_for(selection),
                )
            )
    return HighlightReview(tuple(decisions))


def _gate_margin_ratio(selection: QualitySelection) -> float:
    """How far a candidate's GPMF/road-context evidence clears the hard gate.

    A value near 1.0 means the candidate barely passed
    `highlight_quality.passes_complete_evidence_gate`; larger values mean it
    cleared the gate with room to spare. Only the gate's numeric thresholds are
    used, so no private identifier is involved.
    """
    evidence = selection.scored.evidence
    ratios = (
        evidence.gpmf.gyro_sustained_rad_s / MINIMUM_GYRO_SUSTAINED_RAD_S,
        evidence.gpmf.center_gyro_sustained_rad_s / MINIMUM_CENTER_GYRO_SUSTAINED_RAD_S,
        evidence.road_context_ratio / MINIMUM_ROAD_CONTEXT_RATIO,
    )
    return min(ratios)


def find_highlight_review_borderline_candidates(
    selections: dict[QualitySelectionMethod, tuple[QualitySelection, ...]],
    *,
    score_quantile: float = DEFAULT_BORDERLINE_SCORE_QUANTILE,
    gate_margin_ratio: float = DEFAULT_BORDERLINE_GATE_MARGIN_RATIO,
) -> HighlightReviewBorderlineLog:
    """Flag the weakest automatically-approved candidates for optional review.

    Two independent, non-blocking signals are checked per method group:
    the lowest-scoring fraction of that method's own selection, and any
    candidate whose GPMF/road-context evidence barely cleared the hard gate.
    Neither signal changes the automatic decision; both only add an entry to
    the private borderline log.
    """
    if not 0.0 < score_quantile < 1.0:
        raise ValueError("score_quantile must be between 0 and 1")
    if gate_margin_ratio < 1.0:
        raise ValueError("gate_margin_ratio must be at least 1.0")
    entries: list[HighlightReviewBorderlineEntry] = []
    for method in QualitySelectionMethod:
        group = selections.get(method, ())
        if not group:
            continue
        scores = sorted(selection.scored.score_for(method) for selection in group)
        cutoff_count = max(1, round(len(group) * score_quantile))
        low_score_cutoff = scores[cutoff_count - 1]
        for selection in group:
            reasons: list[HighlightReviewBorderlineReason] = []
            if selection.scored.score_for(method) <= low_score_cutoff:
                reasons.append(HighlightReviewBorderlineReason.LOW_SCORE_MARGIN)
            if _gate_margin_ratio(selection) <= gate_margin_ratio:
                reasons.append(HighlightReviewBorderlineReason.NEAR_GATE_THRESHOLD)
            if reasons:
                entries.append(
                    HighlightReviewBorderlineEntry(
                        candidate_id=highlight_review_candidate_id(selection),
                        method=method,
                        rank=selection.rank,
                        reasons=tuple(reasons),
                    )
                )
    return HighlightReviewBorderlineLog(tuple(entries))


def evaluate_highlight_review(
    selections: dict[QualitySelectionMethod, tuple[QualitySelection, ...]],
    review: HighlightReview,
) -> HighlightReviewResult:
    """Reject stale review data rather than applying it to different candidates."""
    expected = build_highlight_review_template(selections)
    expected_keys = {
        (decision.candidate_id, decision.method, decision.rank) for decision in expected.decisions
    }
    actual_keys = {
        (decision.candidate_id, decision.method, decision.rank) for decision in review.decisions
    }
    if actual_keys != expected_keys:
        raise ValueError("highlight review must contain exactly the current review candidates")
    approved = tuple(
        decision.candidate_id
        for decision in review.decisions
        if decision.status is HighlightReviewStatus.APPROVED
    )
    awaiting = tuple(
        decision.candidate_id
        for decision in review.decisions
        if decision.status is HighlightReviewStatus.AWAITING
    )
    rejected = tuple(
        decision.candidate_id
        for decision in review.decisions
        if decision.status is HighlightReviewStatus.REJECTED
    )
    counts = Counter(reason for decision in review.decisions for reason in decision.reasons)
    return HighlightReviewResult(
        approved_candidate_ids=approved,
        awaiting_candidate_ids=awaiting,
        rejected_candidate_ids=rejected,
        reason_counts=dict(counts),
    )


def update_highlight_review_decision(
    review: HighlightReview,
    *,
    candidate_id: str,
    status: HighlightReviewStatus,
    reasons: tuple[HighlightReviewReason, ...] = (),
) -> HighlightReview:
    """Return a reviewed copy after changing exactly one opaque candidate.

    A reviewer may return a decision to awaiting when correcting a mistake, but
    cannot add, remove, or retarget a candidate identity.
    """
    if not candidate_id:
        raise ValueError("highlight review candidate ID is required")
    updated: list[HighlightReviewDecision] = []
    matched = False
    for decision in review.decisions:
        if decision.candidate_id != candidate_id:
            updated.append(decision)
            continue
        matched = True
        updated.append(
            HighlightReviewDecision(
                candidate_id=decision.candidate_id,
                method=decision.method,
                rank=decision.rank,
                status=status,
                reasons=reasons,
            )
        )
    if not matched:
        raise ValueError("highlight review candidate ID is unknown")
    return HighlightReview(tuple(updated))


def load_or_create_highlight_review(
    path: Path,
    selections: dict[QualitySelectionMethod, tuple[QualitySelection, ...]],
) -> HighlightReview:
    """Preserve a current human review or create a new awaiting template."""
    if path.exists():
        review = load_highlight_review(path)
        evaluate_highlight_review(selections, review)
        return review
    review = build_highlight_review_template(selections)
    write_highlight_review(path, review)
    return review


def load_or_autodecide_highlight_review(
    path: Path,
    selections: dict[QualitySelectionMethod, tuple[QualitySelection, ...]],
) -> HighlightReview:
    """Preserve a prior review (including any manual correction) or auto-decide.

    A prior file may hold either an old awaiting/human-reviewed file or a
    previous automatic decision; either is kept as-is so a human's manual
    correction (via `update_highlight_review_decision`) survives a rerun. Only
    a missing file triggers a fresh automatic decision.
    """
    if path.exists():
        review = load_highlight_review(path)
        evaluate_highlight_review(selections, review)
        return review
    review = auto_decide_highlight_review(selections)
    write_highlight_review(path, review)
    return review


def load_highlight_review(path: Path) -> HighlightReview:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if payload.get("schema_version") != HIGHLIGHT_REVIEW_SCHEMA_VERSION:
        raise ValueError("unsupported highlight review schema")
    return HighlightReview(
        tuple(
            HighlightReviewDecision(
                candidate_id=item["candidate_id"],
                method=QualitySelectionMethod(item["method"]),
                rank=int(item["rank"]),
                status=HighlightReviewStatus(item["status"]),
                reasons=tuple(HighlightReviewReason(reason) for reason in item.get("reasons", [])),
            )
            for item in payload.get("decisions", [])
        )
    )


def write_highlight_review(
    output_path: Path,
    review: HighlightReview,
    *,
    overwrite: bool = False,
) -> Path:
    if output_path.exists() and not overwrite:
        raise FileExistsError(
            "highlight review already exists; choose a new path or pass overwrite=True"
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
            handle.write(json.dumps(review.to_dict(), ensure_ascii=False, indent=2) + "\n")
        os.replace(temporary_path, output_path)
    except BaseException:
        temporary_path.unlink(missing_ok=True)
        raise
    return output_path


def load_highlight_review_borderline_log(path: Path) -> HighlightReviewBorderlineLog:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if payload.get("schema_version") != HIGHLIGHT_REVIEW_BORDERLINE_LOG_SCHEMA_VERSION:
        raise ValueError("unsupported highlight review borderline log schema")
    return HighlightReviewBorderlineLog(
        tuple(
            HighlightReviewBorderlineEntry(
                candidate_id=item["candidate_id"],
                method=QualitySelectionMethod(item["method"]),
                rank=int(item["rank"]),
                reasons=tuple(
                    HighlightReviewBorderlineReason(reason) for reason in item.get("reasons", [])
                ),
            )
            for item in payload.get("entries", [])
        )
    )


def write_highlight_review_borderline_log(
    output_path: Path,
    log: HighlightReviewBorderlineLog,
    *,
    overwrite: bool = True,
) -> Path:
    """Persist the borderline log. Derived, non-human-edited data, so a rerun
    overwrites it by default rather than preserving a stale prior version.
    """
    if output_path.exists() and not overwrite:
        raise FileExistsError(
            "highlight review borderline log already exists; choose a new path or pass "
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
            handle.write(json.dumps(log.to_dict(), ensure_ascii=False, indent=2) + "\n")
        os.replace(temporary_path, output_path)
    except BaseException:
        temporary_path.unlink(missing_ok=True)
        raise
    return output_path
