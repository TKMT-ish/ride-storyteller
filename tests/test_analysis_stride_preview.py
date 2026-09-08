"""Boundary and integration tests for Gate 7.3's stride preview.

The pure filter (`stride_filtered_candidates`) is checked directly against
hand-built candidates so the grid logic is exercised without needing a real
route with turns or stops of its own. `preview_stride_selection` is then
checked against the same synthetic package fixture `test_analysis_compare`
uses, reusing its judgement and ranking helpers so nothing here reaches
Google either.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from app.analysis_stride_preview import (
    AnalysisStridePreviewError,
    preview_stride_selection,
    stride_filtered_candidates,
)
from app.contracts import VideoAnalysis
from app.gemini_selection import JudgedCandidate
from tests.test_analysis_compare import _rank_by_score
from tests.test_analysis_ranking import _judge, _package

_START = datetime(2026, 5, 1, 9, 0, 0, tzinfo=UTC)


def _analysis(*, start_offset_s: float, score: float = 0.5) -> VideoAnalysis:
    return VideoAnalysis(
        asset_id="asset-1",
        start_offset_s=start_offset_s,
        end_offset_s=start_offset_s + 12.0,
        visual_description="a road",
        road_type="highway",
        scenery_tags=("sky",),
        weather_visible="clear",
        visual_interest_score=score,
        story_relevance_score=score,
        confidence=0.9,
        analysis_provider="gemini",
    )


def _candidate(
    event_id: str, *, start_offset_s: float, minute: int = 0, has_analysis: bool = True
) -> JudgedCandidate:
    return JudgedCandidate(
        event_id=event_id,
        start_time=_START + timedelta(minutes=minute),
        duration_s=12.0,
        analysis=_analysis(start_offset_s=start_offset_s) if has_analysis else None,
    )


def test_stride_filtered_candidates_keeps_only_the_coarser_grid() -> None:
    grid = tuple(
        _candidate(f"grid-{i}", start_offset_s=float(i * 30), minute=i) for i in range(5)
    )  # offsets 0, 30, 60, 90, 120

    kept = stride_filtered_candidates(grid, stride_s=60.0, base_stride_s=30.0)

    assert {c.event_id for c in kept} == {"grid-0", "grid-2", "grid-4"}


def test_stride_filtered_candidates_always_keeps_off_grid_windows() -> None:
    """A turn or fixed-shot window is never on the base stride's own grid."""
    on_grid = _candidate("grid-1", start_offset_s=30.0, minute=0)
    off_grid = _candidate("turn-1", start_offset_s=45.37, minute=1)

    kept = stride_filtered_candidates((on_grid, off_grid), stride_s=60.0, base_stride_s=30.0)

    assert {c.event_id for c in kept} == {"turn-1"}


def test_stride_filtered_candidates_identity_at_the_bought_stride() -> None:
    grid = tuple(_candidate(f"grid-{i}", start_offset_s=float(i * 30), minute=i) for i in range(4))

    kept = stride_filtered_candidates(grid, stride_s=30.0, base_stride_s=30.0)

    assert {c.event_id for c in kept} == {c.event_id for c in grid}


def test_stride_filtered_candidates_drops_windows_with_no_analysis() -> None:
    on_grid = _candidate("grid-1", start_offset_s=0.0)
    rankless = _candidate("rankless", start_offset_s=0.0, minute=1, has_analysis=False)

    kept = stride_filtered_candidates((on_grid, rankless), stride_s=60.0, base_stride_s=30.0)

    assert {c.event_id for c in kept} == {"grid-1"}


@pytest.mark.parametrize("stride_s,base_stride_s", [(0.0, 30.0), (30.0, 0.0), (-1.0, 30.0)])
def test_stride_filtered_candidates_rejects_a_non_positive_stride(
    stride_s: float, base_stride_s: float
) -> None:
    with pytest.raises(AnalysisStridePreviewError, match="positive"):
        stride_filtered_candidates((), stride_s=stride_s, base_stride_s=base_stride_s)


def test_stride_filtered_candidates_refuses_to_narrow_the_stride() -> None:
    with pytest.raises(AnalysisStridePreviewError, match="widen"):
        stride_filtered_candidates((), stride_s=15.0, base_stride_s=30.0)


def test_preview_needs_a_bought_judgement(tmp_path: Path) -> None:
    package = _package(tmp_path / "package")
    with pytest.raises(AnalysisStridePreviewError, match="no bought judgement"):
        preview_stride_selection(package, stride_s=60.0)


def test_preview_raises_when_no_candidates_survive_the_coarser_stride(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    package = _package(tmp_path / "package")
    _judge(package, {0: 0.9})
    monkeypatch.setattr(
        "app.analysis_stride_preview.stride_filtered_candidates", lambda *args, **kwargs: ()
    )

    with pytest.raises(AnalysisStridePreviewError, match="no candidates survive"):
        preview_stride_selection(package, stride_s=60.0)


def test_preview_narrows_candidates_and_keeps_the_footage_target(tmp_path: Path) -> None:
    package = _package(tmp_path / "package", recording_s=3600.0)
    scores = {i: 0.9 - 0.01 * i for i in range(20)}
    _judge(package, scores)
    _rank_by_score(package, scores)

    report = preview_stride_selection(package, stride_s=60.0).to_dict()

    assert report["preview"]["candidate_count"] < report["base"]["candidate_count"]
    assert report["base"]["selected_count"] > 0
    assert report["preview"]["selected_count"] > 0
    assert report["shared_selected_count"] <= report["base"]["selected_count"]
    assert report["shared_selected_count"] <= report["base_picks_still_candidates"]
