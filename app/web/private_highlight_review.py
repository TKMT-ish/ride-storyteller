"""Loopback-only access to a private highlight-review package.

The package directory is selected explicitly by a local environment variable.
This module exposes no source paths, source names, offsets, coordinates, frames,
or free-form review text.  Browser clients receive only opaque candidate IDs,
fixed decision codes, and server-owned media URLs.
"""

from __future__ import annotations

import os
from collections import Counter
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import urlencode

from app.config import load_local_environment
from app.video.highlight_quality import QualitySelectionMethod
from app.video.highlight_review import (
    HighlightReview,
    HighlightReviewReason,
    HighlightReviewStatus,
    load_highlight_review,
    update_highlight_review_decision,
    write_highlight_review,
)

PRIVATE_HIGHLIGHT_REVIEW_DIRECTORY_ENV = "RIDE_PRIVATE_HIGHLIGHT_REVIEW_DIRECTORY"


class PrivateHighlightReviewError(RuntimeError):
    """Raised when the configured local review package is unsafe or incomplete."""


@dataclass(frozen=True)
class PrivateHighlightReviewSession:
    """Read and update one explicitly configured local review package."""

    root: Path

    @classmethod
    def from_environment(cls) -> "PrivateHighlightReviewSession":
        local_values = load_local_environment()
        raw_directory = os.environ.get(
            PRIVATE_HIGHLIGHT_REVIEW_DIRECTORY_ENV,
            local_values.get(PRIVATE_HIGHLIGHT_REVIEW_DIRECTORY_ENV, ""),
        ).strip()
        if not raw_directory:
            raise PrivateHighlightReviewError("private highlight review is not configured")
        return cls.from_directory(Path(raw_directory).expanduser())

    @classmethod
    def from_directory(cls, directory: Path) -> "PrivateHighlightReviewSession":
        if directory.is_symlink() or not directory.is_dir():
            raise PrivateHighlightReviewError("private highlight review directory is unavailable")
        root = directory.resolve()
        review_path = root / "highlight-review.json"
        if review_path.is_symlink() or not review_path.is_file():
            raise PrivateHighlightReviewError("private highlight review data is unavailable")
        session = cls(root=root)
        for decision in session.review.decisions:
            session._asset_path(decision.candidate_id, "thumbnail")
            session._asset_path(decision.candidate_id, "media")
        return session

    @property
    def review_path(self) -> Path:
        return self.root / "highlight-review.json"

    @property
    def review(self) -> HighlightReview:
        return load_highlight_review(self.review_path)

    def payload(self) -> dict[str, object]:
        review = self.review
        status_counts = Counter(decision.status.value for decision in review.decisions)
        return {
            "local_only": True,
            "external_data_sent": False,
            "review": {
                "schema_version": "local-highlight-review-v1",
                "candidate_count": len(review.decisions),
                "status_counts": {
                    status.value: status_counts.get(status.value, 0)
                    for status in HighlightReviewStatus
                },
                "candidates": [
                    {
                        "candidate_id": decision.candidate_id,
                        "method": decision.method.value,
                        "rank": decision.rank,
                        "status": decision.status.value,
                        "reasons": [reason.value for reason in decision.reasons],
                        "thumbnail_url": self._url_for(decision.candidate_id, "thumbnail"),
                        "media_url": self._url_for(decision.candidate_id, "media"),
                    }
                    for decision in review.decisions
                ],
            },
        }

    def asset(self, candidate_id: str, kind: str) -> Path:
        return self._asset_path(candidate_id, kind)

    def update(
        self,
        *,
        candidate_id: str,
        status: HighlightReviewStatus,
        reasons: tuple[HighlightReviewReason, ...],
    ) -> dict[str, object]:
        updated = update_highlight_review_decision(
            self.review,
            candidate_id=candidate_id,
            status=status,
            reasons=reasons,
        )
        write_highlight_review(self.review_path, updated, overwrite=True)
        return self.payload()

    def _asset_path(self, candidate_id: str, kind: str) -> Path:
        decision = next(
            (item for item in self.review.decisions if item.candidate_id == candidate_id),
            None,
        )
        if decision is None:
            raise PrivateHighlightReviewError("unknown private review candidate")
        if kind == "thumbnail":
            relative = Path("review-thumbnails") / _thumbnail_name(decision.method, decision.rank)
        elif kind == "media":
            relative = Path(decision.method.value) / f"clip-{decision.rank:02d}.mp4"
        else:
            raise PrivateHighlightReviewError("unknown private review asset")
        candidate_path = self.root / relative
        if candidate_path.is_symlink():
            raise PrivateHighlightReviewError("private review asset is unavailable")
        path = candidate_path.resolve()
        if self.root not in path.parents or not path.is_file():
            raise PrivateHighlightReviewError("private review asset is unavailable")
        return path

    @staticmethod
    def _url_for(candidate_id: str, kind: str) -> str:
        return "/api/private-highlight-review/asset?" + urlencode(
            {"candidate_id": candidate_id, "kind": kind}
        )


def _thumbnail_name(method: QualitySelectionMethod, rank: int) -> str:
    return f"{method.value}-clip-{rank:02d}.jpg"
