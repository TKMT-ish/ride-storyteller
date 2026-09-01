"""Loopback-only human evidence review for a private local review package.

The browser receives opaque review IDs and server-owned media URLs only.  It
never receives event IDs, asset IDs, source names, offsets, coordinates, or
paths.  A human decision here is deliberately separate from highlight-quality
labels: it says only whether the already extracted review clip is acceptable
visual evidence for its candidate event.
"""

from __future__ import annotations

import os
from collections import Counter
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import urlencode

from app.config import load_local_environment
from app.edit import CandidateEvidenceStatus
from app.video import (
    LocalEvidenceDecision,
    LocalEvidenceReview,
    evaluate_local_evidence_review,
    load_local_evidence_review,
    load_local_review_clip_manifest,
    load_resolved_candidate_export,
    write_local_evidence_review,
)

PRIVATE_EVIDENCE_REVIEW_DIRECTORY_ENV = "RIDE_PRIVATE_EVIDENCE_REVIEW_DIRECTORY"
_HUMAN_REVIEW_SOURCE = "human_local_review"


class PrivateEvidenceReviewError(RuntimeError):
    """Raised when a configured local evidence-review package is unsafe."""


@dataclass(frozen=True)
class PrivateEvidenceReviewSession:
    """Read and update one explicitly configured local evidence-review package."""

    root: Path

    @classmethod
    def from_environment(cls) -> "PrivateEvidenceReviewSession":
        local_values = load_local_environment()
        raw_directory = os.environ.get(
            PRIVATE_EVIDENCE_REVIEW_DIRECTORY_ENV,
            local_values.get(PRIVATE_EVIDENCE_REVIEW_DIRECTORY_ENV, ""),
        ).strip()
        if not raw_directory:
            raise PrivateEvidenceReviewError("private evidence review is not configured")
        return cls.from_directory(Path(raw_directory).expanduser())

    @classmethod
    def from_directory(cls, directory: Path) -> "PrivateEvidenceReviewSession":
        if directory.is_symlink() or not directory.is_dir():
            raise PrivateEvidenceReviewError("private evidence review directory is unavailable")
        root = directory.resolve()
        required_paths = (
            root / "ride-storyteller-candidates.json",
            root / "evidence-review.json",
            root / "review-clip-manifest.json",
            root / "review-clips",
        )
        if any(path.is_symlink() or not path.exists() for path in required_paths):
            raise PrivateEvidenceReviewError("private evidence review data is unavailable")
        if not required_paths[-1].is_dir():
            raise PrivateEvidenceReviewError("private evidence review data is unavailable")
        session = cls(root=root)
        session._validated_state()
        for review_id in session.review_ids:
            session.asset(review_id)
        return session

    @property
    def review_path(self) -> Path:
        return self.root / "evidence-review.json"

    @property
    def review_ids(self) -> tuple[str, ...]:
        return tuple(
            _review_id(index)
            for index, _clip in enumerate(self._manifest(), start=1)
        )

    def payload(self) -> dict[str, object]:
        _clips, review, manifest = self._validated_state()
        decisions = {decision.event_id: decision for decision in review.decisions}
        status_counts = Counter(
            decisions[item.event_id].evidence_status.value for item in manifest
        )
        return {
            "local_only": True,
            "external_data_sent": False,
            "next_gate": _next_evidence_gate(review),
            "review": {
                "schema_version": "private-evidence-review-v1",
                "candidate_count": len(manifest),
                "status_counts": {
                    status.value: status_counts.get(status.value, 0)
                    for status in CandidateEvidenceStatus
                },
                "candidates": [
                    {
                        "review_id": _review_id(index),
                        "status": decisions[item.event_id].evidence_status.value,
                        "media_url": self._url_for(_review_id(index)),
                    }
                    for index, item in enumerate(manifest, start=1)
                ],
            },
        }

    def asset(self, review_id: str) -> Path:
        _clips, _review, manifest = self._validated_state()
        index = _review_index(review_id, len(manifest))
        output_file_name = manifest[index].output_file_name
        candidate_path = self.root / "review-clips" / output_file_name
        if candidate_path.is_symlink():
            raise PrivateEvidenceReviewError("private evidence review asset is unavailable")
        path = candidate_path.resolve()
        review_root = (self.root / "review-clips").resolve()
        if review_root not in path.parents or not path.is_file():
            raise PrivateEvidenceReviewError("private evidence review asset is unavailable")
        return path

    def update(
        self,
        *,
        review_id: str,
        status: CandidateEvidenceStatus,
    ) -> dict[str, object]:
        clips, review, manifest = self._validated_state()
        index = _review_index(review_id, len(manifest))
        selected_event_id = manifest[index].event_id
        decision_by_event = {decision.event_id: decision for decision in review.decisions}
        if selected_event_id not in decision_by_event:
            raise PrivateEvidenceReviewError("private evidence review data is unavailable")
        updated = LocalEvidenceReview(
            tuple(
                LocalEvidenceDecision(
                    event_id=decision.event_id,
                    evidence_status=(
                        status
                        if decision.event_id == selected_event_id
                        else decision.evidence_status
                    ),
                    evidence_source=(
                        None
                        if decision.event_id == selected_event_id
                        and status is CandidateEvidenceStatus.AWAITING_VIDEO_EVIDENCE
                        else (
                            _HUMAN_REVIEW_SOURCE
                            if decision.event_id == selected_event_id
                            else decision.evidence_source
                        )
                    ),
                )
                for decision in review.decisions
            )
        )
        evaluate_local_evidence_review(clips, updated)
        write_local_evidence_review(self.review_path, updated, overwrite=True)
        return self.payload()

    def _manifest(self):
        return load_local_review_clip_manifest(self.root / "review-clip-manifest.json")

    def _validated_state(self):
        clips = load_resolved_candidate_export(self.root / "ride-storyteller-candidates.json")
        review = load_local_evidence_review(self.review_path)
        manifest = self._manifest()
        evaluate_local_evidence_review(clips, review)
        clip_by_event = {clip.event_id: clip for clip in clips}
        if len(manifest) != len(clip_by_event) or {
            item.event_id for item in manifest
        } != set(clip_by_event):
            raise PrivateEvidenceReviewError("private evidence review manifest is incomplete")
        if any(clip_by_event[item.event_id].asset_id != item.asset_id for item in manifest):
            raise PrivateEvidenceReviewError("private evidence review manifest is inconsistent")
        return clips, review, manifest

    @staticmethod
    def _url_for(review_id: str) -> str:
        return "/api/private-evidence-review/asset?" + urlencode({"review_id": review_id})


def _next_evidence_gate(review: LocalEvidenceReview) -> str:
    """Return the next local action without claiming story-render readiness.

    This deliberately reflects only human evidence decisions.  A later local
    pipeline pass still validates candidate duration and timestamp matching
    before it may run the Director or renderer.
    """
    statuses = {decision.evidence_status for decision in review.decisions}
    if CandidateEvidenceStatus.REJECTED in statuses:
        return "replace_rejected_candidate_clips"
    if CandidateEvidenceStatus.AWAITING_VIDEO_EVIDENCE in statuses:
        return "human_visual_evidence_review"
    return "revalidate_local_pipeline"


def _review_id(index: int) -> str:
    return f"review-{index:03d}"


def _review_index(review_id: str, length: int) -> int:
    if not review_id.startswith("review-"):
        raise PrivateEvidenceReviewError("unknown private evidence review candidate")
    try:
        index = int(review_id.removeprefix("review-")) - 1
    except ValueError as error:
        raise PrivateEvidenceReviewError("unknown private evidence review candidate") from error
    if index < 0 or index >= length or _review_id(index + 1) != review_id:
        raise PrivateEvidenceReviewError("unknown private evidence review candidate")
    return index
