"""Compare Gate 7.2's rank-only path against the judged-and-ranked one.

`app.analysis_tournament` made the decision this used to leave open:
`select_judged_candidates(requires_analysis=False)` lets a tournament's
`ranks` alone carry a ride through selection, no `VideoAnalysis` required.
What the roadmap (7.2) still asks for is the other half -- on a ride that
has bought *both* a judgement+ranking and a tournament ranking, say what
each keeps and what each would have cost, so the trade can be measured
rather than assumed.

Both paths choose from the same candidates: the windows a bought judgement
named (a tournament ranks windows a judgement never described, but ranks
them by event_id, so the judged candidate list also names every window a
tournament could place). The only difference between the two calls is
`requires_analysis` and which ranking each reads -- the judged path keeps
each candidate's `VideoAnalysis` as `select_judged_candidates` already used
it (the rider-in-frame and car-park floors, the road-family tie-break); the
tournament path is asked to pretend that judgement was never bought, since
a real rank-only ride would have none, and falls back to the tournament's
own order for every tie.

Sends nothing -- both rankings are already paid for and sitting in the
package; this only reads them.
"""

from __future__ import annotations

from dataclasses import dataclass, replace
from pathlib import Path

from app.analysis_ranking import plan_ranking_cost, ranks_for
from app.analysis_run import plan_analysis_run
from app.analysis_tournament import plan_tournament_cost, tournament_ranks_for
from app.gemini_selection import select_judged_candidates
from app.private_journey_film import _judged_candidates
from app.story_pacing import DEFAULT_FOOTAGE_TARGET_S
from app.video import load_video_catalog

LOCAL_VIDEO_CATALOG_FILE_NAME = "local-video-catalog.json"


class AnalysisCompareError(RuntimeError):
    """Raised when a package cannot be compared as asked."""


@dataclass(frozen=True)
class PathSelection:
    """What one selection path kept, and what buying it costs."""

    selected_count: int
    footage_duration_s: float
    estimated_jpy: float

    def to_dict(self) -> dict[str, object]:
        return {
            "selected_count": self.selected_count,
            "footage_duration_s": round(self.footage_duration_s, 3),
            "estimated_jpy": self.estimated_jpy,
        }


def compare_selection_paths(
    package_directory: Path, *, footage_target_s: float = DEFAULT_FOOTAGE_TARGET_S
) -> dict[str, object]:
    """What the judged-and-ranked path keeps against what the tournament alone would.

    Raises if the package is missing either a bought judgement or a bought
    tournament ranking -- there is nothing to compare a ranking against.
    """
    catalog = load_video_catalog(package_directory / LOCAL_VIDEO_CATALOG_FILE_NAME)
    judged = _judged_candidates(package_directory, catalog)
    if judged is None:
        raise AnalysisCompareError("this package carries no bought judgement to compare")

    judged_ranks = ranks_for(package_directory)
    tournament_ranks = tournament_ranks_for(package_directory)
    if tournament_ranks is None:
        raise AnalysisCompareError("this package carries no bought tournament ranking")

    judge_cost = plan_analysis_run(package_directory).cascade.total_jpy
    rank_cost = plan_ranking_cost(package_directory)["estimated_jpy"]
    tournament_cost = plan_tournament_cost(package_directory)["estimated_jpy"]

    judged_selection = select_judged_candidates(
        judged, ranks=judged_ranks, footage_target_s=footage_target_s
    )
    # A tournament never describes a window, so the ride it would actually
    # carry has no VideoAnalysis at all; stripping it here rather than
    # passing the bought one is what makes this a fair rank-only comparison,
    # not a best-of-both-worlds one nobody could actually buy.
    rankless = tuple(replace(candidate, analysis=None) for candidate in judged)
    tournament_selection = select_judged_candidates(
        rankless, ranks=tournament_ranks, footage_target_s=footage_target_s, requires_analysis=False
    )

    judged_path = PathSelection(
        selected_count=len(judged_selection.selected_event_ids),
        footage_duration_s=judged_selection.footage_duration_s,
        estimated_jpy=round(judge_cost + rank_cost, 2),
    )
    tournament_path = PathSelection(
        selected_count=len(tournament_selection.selected_event_ids),
        footage_duration_s=tournament_selection.footage_duration_s,
        estimated_jpy=tournament_cost,
    )
    shared = set(judged_selection.selected_event_ids) & set(tournament_selection.selected_event_ids)
    return {
        "candidate_count": len(judged),
        "judged_and_ranked": judged_path.to_dict(),
        "tournament_only": tournament_path.to_dict(),
        "shared_selected_count": len(shared),
    }
