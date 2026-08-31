"""Persist structured human feedback for private highlight-review candidates.

This contract stores only opaque candidate IDs, selection method/rank, and fixed
reason codes. It intentionally excludes source paths, file names, timestamps,
coordinates, frames, and free-form notes so the feedback can be used for local
threshold evaluation without copying private-media identifiers into text fields.
"""

from __future__ import annotations

import hashlib
import json
from collections import Counter
from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path

from .highlight_quality import QualitySelection, QualitySelectionMethod

HIGHLIGHT_REVIEW_SCHEMA_VERSION = "local-highlight-review-v1"


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
    output_path.write_text(
        json.dumps(review.to_dict(), ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    return output_path
