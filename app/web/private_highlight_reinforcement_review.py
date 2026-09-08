"""Loopback-only private review of unresolved highlight reinforcement conflicts.

The review package directory is selected explicitly by a local environment
variable distinct from `app.web.private_highlight_review`'s configuration
(`PRIVATE_HIGHLIGHT_REINFORCEMENT_REVIEW_DIRECTORY_ENV`). This module exposes
no event IDs, candidate IDs, asset IDs, offsets, timestamps, source paths,
file names, coordinates, scores, or credentials. Browser clients receive only
per-session opaque review tokens, `method`, `rank`, and server-owned
thumbnail/media URLs.

A review token names one position in the configured package's current
conflict list (`highlight-reinforcement-conflicts.json`, written by
`app.video.highlight_story_bridge.write_highlight_reinforcement_conflicts`).
It is only meaningful for that file's current contents; it is never accepted
as, or resolved from, a raw `event_id`/`candidate_id` sent by a browser, and
every token is re-validated against a fresh read of that file before a save
is trusted.

A saved choice is written through the existing strict
`HighlightReinforcementSelectionSet` persistence
(`highlight-reinforcement-selections.json` in the same directory) so it
reaches `reinforce_resolved_clips_with_highlights` unchanged. This module
does not read source video, call Director, or trigger a render; it only
records which candidate a human picked for one conflicted clip.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import urlencode

from app.config import load_local_environment
from app.video.highlight_quality import QualitySelectionMethod
from app.video.highlight_story_bridge import (
    HighlightReinforcementConflict,
    HighlightReinforcementSelection,
    HighlightReinforcementSelectionSet,
    load_highlight_reinforcement_conflicts,
    load_highlight_reinforcement_selections,
    write_highlight_reinforcement_selections,
)

PRIVATE_HIGHLIGHT_REINFORCEMENT_REVIEW_DIRECTORY_ENV = (
    "RIDE_PRIVATE_HIGHLIGHT_REINFORCEMENT_REVIEW_DIRECTORY"
)
_CONFLICTS_FILE_NAME = "highlight-reinforcement-conflicts.json"
_SELECTIONS_FILE_NAME = "highlight-reinforcement-selections.json"
_TOKEN_PREFIX = "reinforcement-"


class PrivateHighlightReinforcementReviewError(RuntimeError):
    """Raised when the configured local conflict review package is unsafe."""


@dataclass(frozen=True)
class PrivateHighlightReinforcementReviewSession:
    """Read one explicitly configured package's unresolved conflicts.

    Saved choices are written back into the same directory's
    `HighlightReinforcementSelectionSet` sidecar. Nothing outside this one
    configured directory is read: no parent-directory scan, no fallback to
    another package's layout.
    """

    root: Path

    @classmethod
    def from_environment(cls) -> "PrivateHighlightReinforcementReviewSession":
        local_values = load_local_environment()
        raw_directory = os.environ.get(
            PRIVATE_HIGHLIGHT_REINFORCEMENT_REVIEW_DIRECTORY_ENV,
            local_values.get(PRIVATE_HIGHLIGHT_REINFORCEMENT_REVIEW_DIRECTORY_ENV, ""),
        ).strip()
        if not raw_directory:
            raise PrivateHighlightReinforcementReviewError(
                "private highlight reinforcement review is not configured"
            )
        return cls.from_directory(Path(raw_directory).expanduser())

    @classmethod
    def from_directory(cls, directory: Path) -> "PrivateHighlightReinforcementReviewSession":
        if directory.is_symlink() or not directory.is_dir():
            raise PrivateHighlightReinforcementReviewError(
                "private highlight reinforcement review directory is unavailable"
            )
        root = directory.resolve()
        conflicts_path = root / _CONFLICTS_FILE_NAME
        if conflicts_path.is_symlink() or not conflicts_path.is_file():
            raise PrivateHighlightReinforcementReviewError(
                "private highlight reinforcement review data is unavailable"
            )
        session = cls(root=root)
        options = session._options()
        for option in options:
            session._asset_path(option, "thumbnail")
            session._asset_path(option, "media")
        return session

    @property
    def conflicts_path(self) -> Path:
        return self.root / _CONFLICTS_FILE_NAME

    @property
    def selections_path(self) -> Path:
        return self.root / _SELECTIONS_FILE_NAME

    def payload(self) -> dict[str, object]:
        options = self._options()
        views = [self._option_view(index, option) for index, option in enumerate(options)]
        groups: list[list[dict[str, object]]] = []
        group_index_by_event: dict[str, int] = {}
        for option, view in zip(options, views, strict=True):
            group_index = group_index_by_event.setdefault(option.event_id, len(groups))
            if group_index == len(groups):
                groups.append([])
            groups[group_index].append(view)
        return {
            "local_only": True,
            "external_data_sent": False,
            "review": {
                "schema_version": "private-highlight-reinforcement-review-v1",
                "conflict_count": len(groups),
                "conflict_option_count": len(options),
                "conflicts": [{"options": group} for group in groups],
            },
        }

    def asset(self, review_token: str, kind: str) -> Path:
        option = self._option_for_token(review_token)
        return self._asset_path(option, kind)

    def update(self, *, review_token: str) -> dict[str, object]:
        """Save one explicit choice, replacing only its own event's selection.

        Re-validates the token against a freshly loaded conflict list rather
        than trusting the one read earlier in the same request cycle, so a
        token that no longer maps to an available, unambiguous candidate
        (the underlying package changed, or the candidate is gone) is
        rejected rather than silently applied.
        """
        current_options = self._options()
        index = _review_index(review_token, len(current_options))
        option = current_options[index]

        existing = self._selections()
        preserved = tuple(
            selection
            for selection in existing.selections
            if selection.event_id != option.event_id
            and selection.candidate_id != option.candidate_id
        )
        updated = HighlightReinforcementSelectionSet(
            (*preserved, HighlightReinforcementSelection(option.event_id, option.candidate_id))
        )
        write_highlight_reinforcement_selections(self.selections_path, updated, overwrite=True)
        return self.payload()

    def _options(self) -> tuple[HighlightReinforcementConflict, ...]:
        """The current conflict list, in its own deterministic order.

        Token position names an index into exactly this order, so it is
        recomputed fresh (never cached) everywhere a token is resolved.
        """
        return load_highlight_reinforcement_conflicts(self.conflicts_path).conflicts

    def _selections(self) -> HighlightReinforcementSelectionSet:
        path = self.selections_path
        if path.is_symlink():
            raise PrivateHighlightReinforcementReviewError(
                "private highlight reinforcement review data is unavailable"
            )
        if not path.is_file():
            return HighlightReinforcementSelectionSet(())
        return load_highlight_reinforcement_selections(path)

    def _option_for_token(self, review_token: str) -> HighlightReinforcementConflict:
        options = self._options()
        index = _review_index(review_token, len(options))
        return options[index]

    def _option_view(self, index: int, option: HighlightReinforcementConflict) -> dict[str, object]:
        token = _review_token(index + 1)
        return {
            "review_token": token,
            "method": option.method.value,
            "rank": option.rank,
            "thumbnail_url": self._url_for(token, "thumbnail"),
            "media_url": self._url_for(token, "media"),
        }

    def _asset_path(self, option: HighlightReinforcementConflict, kind: str) -> Path:
        if kind == "thumbnail":
            relative = Path("review-thumbnails") / _thumbnail_name(option.method, option.rank)
        elif kind == "media":
            relative = Path(option.method.value) / f"clip-{option.rank:02d}.mp4"
        else:
            raise PrivateHighlightReinforcementReviewError(
                "unknown private highlight reinforcement review asset"
            )
        candidate_path = self.root / relative
        if candidate_path.is_symlink():
            raise PrivateHighlightReinforcementReviewError(
                "private highlight reinforcement review asset is unavailable"
            )
        path = candidate_path.resolve()
        if self.root not in path.parents or not path.is_file():
            raise PrivateHighlightReinforcementReviewError(
                "private highlight reinforcement review asset is unavailable"
            )
        return path

    @staticmethod
    def _url_for(review_token: str, kind: str) -> str:
        return "/api/private-highlight-reinforcement-review/asset?" + urlencode(
            {"review_token": review_token, "kind": kind}
        )


def _thumbnail_name(method: QualitySelectionMethod, rank: int) -> str:
    return f"{method.value}-clip-{rank:02d}.jpg"


def _review_token(index: int) -> str:
    return f"{_TOKEN_PREFIX}{index:03d}"


def _review_index(review_token: str, length: int) -> int:
    if not isinstance(review_token, str) or not review_token.startswith(_TOKEN_PREFIX):
        raise PrivateHighlightReinforcementReviewError(
            "unknown private highlight reinforcement review token"
        )
    try:
        index = int(review_token.removeprefix(_TOKEN_PREFIX)) - 1
    except ValueError as error:
        raise PrivateHighlightReinforcementReviewError(
            "unknown private highlight reinforcement review token"
        ) from error
    if index < 0 or index >= length or _review_token(index + 1) != review_token:
        raise PrivateHighlightReinforcementReviewError(
            "unknown private highlight reinforcement review token"
        )
    return index
