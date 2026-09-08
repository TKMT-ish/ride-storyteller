"""Preview a coarser stride against footage that was already judged (Gate 7.3).

Buying a fresh judgement at a new stride to see whether the film would
still hold together would cost money for a question a stride change does
not actually need paid for: the windows a coarser stride keeps are a
strict subset of a finer one already bought, because
`app.footage_candidates.enumerate_footage_candidates` starts every
recording's offset at zero and steps by the stride -- a run at 60s is
exactly the run at 30s with every other grid window dropped. The turn
windows (Q1) and the fixed shots (the day's proven moments) are not on
that grid at all; they are placed independently of the stride, and a
coarser run would still buy every one of them (`app.analysis_run`).

So this filters a package's already-judged, already-ranked candidates down
to the subset a coarser stride would have produced, and runs the same
selection the film runs over what remains. Nothing is judged again,
uploaded, or sent anywhere.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from app.analysis_ranking import ranks_for
from app.footage_candidates import DEFAULT_STRIDE_S
from app.gemini_selection import JudgedCandidate, select_judged_candidates
from app.private_journey_film import _judged_candidates
from app.story_pacing import DEFAULT_FOOTAGE_TARGET_S
from app.video import load_video_catalog

LOCAL_VIDEO_CATALOG_FILE_NAME = "local-video-catalog.json"

# A window's offset within its recording lands on a stride grid point to
# within a few milliseconds (rounding on write, `AnalysedEvent.to_dict`); a
# turn or fixed-shot window, placed at a GPS timestamp, essentially never
# lands exactly on one by chance.
GRID_TOLERANCE_S = 0.05


class AnalysisStridePreviewError(ValueError):
    """Raised when a coarser stride cannot be previewed for this package."""


def _on_grid(offset_s: float, step_s: float, *, tolerance_s: float = GRID_TOLERANCE_S) -> bool:
    """Whether `offset_s` falls on a grid stepped by `step_s` from zero."""
    remainder = offset_s % step_s
    return remainder <= tolerance_s or step_s - remainder <= tolerance_s


def stride_filtered_candidates(
    judged: tuple[JudgedCandidate, ...],
    *,
    stride_s: float,
    base_stride_s: float = DEFAULT_STRIDE_S,
) -> tuple[JudgedCandidate, ...]:
    """What a package judged at `base_stride_s` would carry at a coarser `stride_s`.

    A candidate stays if it was never on the base stride's grid (a turn or
    fixed-shot window, unaffected by the stride) or if it still lands on
    the coarser grid. `stride_s` narrower than `base_stride_s` raises: that
    would need windows nobody bought, not fewer of the ones that were.
    """
    if stride_s <= 0 or base_stride_s <= 0:
        raise AnalysisStridePreviewError("a stride must be positive")
    if stride_s < base_stride_s - GRID_TOLERANCE_S:
        raise AnalysisStridePreviewError(
            "a preview can only widen the stride this package was judged at, not narrow it"
        )

    kept = []
    for candidate in judged:
        if candidate.analysis is None:
            continue  # nothing here says whether this window was ever on the grid
        offset_s = candidate.analysis.start_offset_s
        if not _on_grid(offset_s, base_stride_s):
            kept.append(candidate)  # a turn or fixed-shot window: the stride never touched it
        elif _on_grid(offset_s, stride_s):
            kept.append(candidate)
    return tuple(kept)


@dataclass(frozen=True)
class StridePreview:
    """What the film keeps at the bought stride against a coarser preview."""

    base_candidate_count: int
    base_selected_count: int
    base_footage_duration_s: float
    preview_candidate_count: int
    preview_selected_count: int
    preview_footage_duration_s: float
    base_picks_still_candidates: int
    shared_selected_count: int

    def to_dict(self) -> dict[str, object]:
        return {
            "base": {
                "candidate_count": self.base_candidate_count,
                "selected_count": self.base_selected_count,
                "footage_duration_s": round(self.base_footage_duration_s, 3),
            },
            "preview": {
                "candidate_count": self.preview_candidate_count,
                "selected_count": self.preview_selected_count,
                "footage_duration_s": round(self.preview_footage_duration_s, 3),
            },
            "base_picks_still_candidates": self.base_picks_still_candidates,
            "shared_selected_count": self.shared_selected_count,
        }


def preview_stride_selection(
    package_directory: Path,
    *,
    stride_s: float,
    base_stride_s: float = DEFAULT_STRIDE_S,
    footage_target_s: float = DEFAULT_FOOTAGE_TARGET_S,
) -> StridePreview:
    """Compare a package's bought selection against a coarser stride's.

    Reads what was already judged and ranked; sends nothing.
    """
    catalog = load_video_catalog(package_directory / LOCAL_VIDEO_CATALOG_FILE_NAME)
    judged = _judged_candidates(package_directory, catalog)
    if judged is None:
        raise AnalysisStridePreviewError("this package carries no bought judgement to preview")

    ranks = ranks_for(package_directory)
    base_selection = select_judged_candidates(
        judged, ranks=ranks, footage_target_s=footage_target_s
    )

    narrowed = stride_filtered_candidates(judged, stride_s=stride_s, base_stride_s=base_stride_s)
    if not narrowed:
        raise AnalysisStridePreviewError("no candidates survive at this stride")
    preview_selection = select_judged_candidates(
        narrowed, ranks=ranks, footage_target_s=footage_target_s
    )

    narrowed_ids = {c.event_id for c in narrowed}
    base_ids = set(base_selection.selected_event_ids)
    preview_ids = set(preview_selection.selected_event_ids)
    return StridePreview(
        base_candidate_count=len(judged),
        base_selected_count=len(base_ids),
        base_footage_duration_s=base_selection.footage_duration_s,
        preview_candidate_count=len(narrowed),
        preview_selected_count=len(preview_ids),
        preview_footage_duration_s=preview_selection.footage_duration_s,
        base_picks_still_candidates=len(base_ids & narrowed_ids),
        shared_selected_count=len(base_ids & preview_ids),
    )
