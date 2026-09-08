"""Synthetic-fixture tests for comparing the judged+ranked and tournament paths.

Reuses `tests.test_analysis_ranking`'s package and judgement fixtures, then
adds a window ranking and a tournament ranking on top -- both already-bought
artefacts `app.analysis_compare` only reads. Nothing here reaches Google.
"""

from __future__ import annotations

from dataclasses import replace
from pathlib import Path

import pytest

from app.analysis_compare import AnalysisCompareError, compare_selection_paths
from app.analysis_ranking import WindowRanking, ranks_for, write_window_ranking
from app.analysis_run import plan_analysis_run
from app.analysis_tournament import (
    TournamentRanking,
    tournament_ranks_for,
    write_tournament_ranking,
)
from app.gemini_selection import select_judged_candidates
from app.private_journey_film import _judged_candidates
from app.video import load_video_catalog
from tests.test_analysis_ranking import _judge, _package


def _rank_by_score(package: Path, scores: dict[int, float]) -> None:
    """A window ranking with the same order `_judge`'s scores imply."""
    plan = plan_analysis_run(package)
    ordered = sorted(range(len(plan.candidates)), key=lambda i: -scores.get(i, 0.3))
    ranks = {plan.candidates[i].event_id: rank for rank, i in enumerate(ordered, start=1)}
    write_window_ranking(package / "gemini-window-ranking.json", WindowRanking("gemini", ranks))


def _rank_by_tournament(package: Path, order: dict[int, float]) -> None:
    """A tournament ranking, independent of whatever `_judge` scored."""
    plan = plan_analysis_run(package)
    ordered = sorted(range(len(plan.candidates)), key=lambda i: -order.get(i, 0.0))
    ranks = {plan.candidates[i].event_id: rank for rank, i in enumerate(ordered, start=1)}
    write_tournament_ranking(
        package / "gemini-tournament-ranking.json", TournamentRanking("gemini", ranks)
    )


def test_compare_needs_a_bought_judgement(tmp_path: Path) -> None:
    package = _package(tmp_path / "package")
    with pytest.raises(AnalysisCompareError, match="no bought judgement"):
        compare_selection_paths(package)


def test_compare_needs_a_bought_tournament_ranking(tmp_path: Path) -> None:
    package = _package(tmp_path / "package")
    _judge(package, {0: 0.9, 1: 0.8, 2: 0.7})
    with pytest.raises(AnalysisCompareError, match="no bought tournament ranking"):
        compare_selection_paths(package)


def test_compare_reports_both_paths_with_consistent_cost(tmp_path: Path) -> None:
    package = _package(tmp_path / "package", recording_s=3600.0)
    _judge(package, {i: 0.9 - 0.01 * i for i in range(20)})
    _rank_by_score(package, {i: 0.9 - 0.01 * i for i in range(20)})
    _rank_by_tournament(package, {i: 0.9 - 0.01 * i for i in range(20)})

    report = compare_selection_paths(package)

    assert report["candidate_count"] == len(plan_analysis_run(package).candidates)
    judged = report["judged_and_ranked"]
    tournament = report["tournament_only"]
    assert judged["selected_count"] > 0
    assert tournament["selected_count"] > 0
    assert judged["footage_duration_s"] > 0
    assert tournament["footage_duration_s"] > 0
    # Every candidate scored and ranked alike by both fixtures, so the two
    # paths should agree closely on what they keep.
    assert report["shared_selected_count"] > 0
    # The judged path's bill is a judgement plus a ranking; the tournament's
    # is only its own comparisons -- the saving Gate 7.2 was built for.
    assert judged["estimated_jpy"] > tournament["estimated_jpy"]


def test_compare_matches_calling_select_judged_candidates_directly(tmp_path: Path) -> None:
    """The plumbing, checked against the functions it wires together.

    `compare_selection_paths` is not its own selection logic -- it is
    `_judged_candidates` plus two calls to `select_judged_candidates`, one of
    them stripped of `VideoAnalysis` and switched to `requires_analysis=False`.
    This holds it to exactly that, independent of whichever floors or ties a
    given fixture happens to trigger.
    """
    package = _package(tmp_path / "package")
    scores = {0: 0.95, 10: 0.5, 20: 0.4}
    _judge(package, scores)
    _rank_by_score(package, scores)
    _rank_by_tournament(package, scores)

    report = compare_selection_paths(package)

    catalog = load_video_catalog(package / "local-video-catalog.json")
    judged = _judged_candidates(package, catalog)
    expected_judged = select_judged_candidates(judged, ranks=ranks_for(package))
    rankless = tuple(replace(c, analysis=None) for c in judged)
    expected_tournament = select_judged_candidates(
        rankless, ranks=tournament_ranks_for(package), requires_analysis=False
    )

    assert report["judged_and_ranked"]["selected_count"] == len(expected_judged.selected_event_ids)
    assert report["judged_and_ranked"]["footage_duration_s"] == pytest.approx(
        expected_judged.footage_duration_s
    )
    assert report["tournament_only"]["selected_count"] == len(
        expected_tournament.selected_event_ids
    )
    assert report["tournament_only"]["footage_duration_s"] == pytest.approx(
        expected_tournament.footage_duration_s
    )
    assert report["shared_selected_count"] == len(
        set(expected_judged.selected_event_ids) & set(expected_tournament.selected_event_ids)
    )
