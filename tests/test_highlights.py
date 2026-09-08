"""Synthetic-fixture tests for choosing the opening's highlights."""

from __future__ import annotations

from dataclasses import replace
from datetime import UTC, datetime, timedelta

import pytest

from app.contracts import VideoAnalysis
from app.gemini_selection import JudgedCandidate
from app.highlights import photogenic, pick_highlights, subject_of

_T0 = datetime(2026, 5, 1, 9, 0, 0, tzinfo=UTC)


def _analysis(description: str, *, interest: float = 0.6, **fields) -> VideoAnalysis:
    return VideoAnalysis(
        asset_id="asset-synthetic-1",
        start_offset_s=0.0,
        end_offset_s=12.0,
        visual_description=description,
        road_type="rural highway",
        scenery_tags=(),
        weather_visible="clear",
        visual_interest_score=interest,
        story_relevance_score=0.5,
        confidence=0.9,
        analysis_provider="gemini",
        **fields,
    )


def _window(name: str, minutes: float, analysis: VideoAnalysis) -> JudgedCandidate:
    return JudgedCandidate(
        event_id=name,
        start_time=_T0 + timedelta(minutes=minutes),
        duration_s=12.0,
        analysis=analysis,
    )


def test_the_models_photogenic_answer_is_used_and_its_words_stand_in_for_older_records() -> None:
    asked = _window("a", 0, _analysis("a road", photogenic_score=0.9, highlight_subject="water"))
    older = _window("b", 0, _analysis("a wide view over the lake and mountains", interest=0.8))
    dull = _window("c", 0, _analysis("a queue of traffic at an intersection", interest=0.5))

    assert photogenic(asked) == 0.9 and subject_of(asked) == "water"
    assert photogenic(older) is not None and photogenic(older) >= 0.8
    assert subject_of(older) in ("mountains", "water")
    assert photogenic(dull) is not None and photogenic(dull) < 0.4


def test_four_pictures_distinct_in_subject_spread_out_and_in_ride_order() -> None:
    windows = (
        _window("coast1", 10, _analysis("x", photogenic_score=0.95, highlight_subject="water")),
        _window("coast2", 15, _analysis("x", photogenic_score=0.94, highlight_subject="water")),
        _window("town", 60, _analysis("x", photogenic_score=0.8, highlight_subject="cityscape")),
        _window("hills", 120, _analysis("x", photogenic_score=0.85, highlight_subject="mountains")),
        _window("view", 200, _analysis("x", photogenic_score=0.7, highlight_subject="vista")),
        _window("plain", 240, _analysis("x", photogenic_score=0.3, highlight_subject="none")),
    )

    picked = pick_highlights(windows, ride_start=_T0, ride_end=_T0 + timedelta(hours=5))

    assert [h.event_id for h in picked] == ["coast1", "town", "hills", "view"]


def test_a_second_pass_fills_the_four_when_subjects_run_out() -> None:
    windows = tuple(
        _window(
            f"w{i}",
            i * 30,
            _analysis("x", photogenic_score=0.9 - i * 0.01, highlight_subject="water"),
        )
        for i in range(6)
    )

    picked = pick_highlights(windows, ride_start=_T0, ride_end=_T0 + timedelta(hours=5))

    assert len(picked) == 4
    assert [h.event_id for h in picked] == sorted(
        (h.event_id for h in picked), key=lambda e: int(e[1:])
    )


def test_the_rider_a_room_and_a_home_never_open_the_film() -> None:
    """The owner's rules (2026-09-06 point 6, 2026-09-07): the rider large in
    the mirror, a museum's inside, and anything that could say whose house
    this is stay out of the opening, however well the model liked them."""
    mirror = _window("m", 0, _analysis("the mirror reflecting the rider", photogenic_score=0.95))
    room = _window(
        "i",
        20,
        _analysis("the interior of a museum hall", photogenic_score=0.95, stationary="no"),
    )
    home = _window(
        "h", 40, _analysis("the driveway of a house", photogenic_score=0.95, stationary="no")
    )
    stop = _window(
        "s",
        60,
        _analysis(
            "a parking lot with a view",
            photogenic_score=0.9,
            highlight_subject="rest_stop",
            stationary="no",
        ),
    )
    dull = _window(
        "d", 90, _analysis("x", photogenic_score=0.4, highlight_subject="vista", stationary="no")
    )

    picked = pick_highlights(
        (mirror, room, home, stop, dull),
        ride_start=_T0,
        ride_end=_T0 + timedelta(hours=2),
        count=1,
    )

    assert [h.event_id for h in picked] == ["s"]
    # A plain day still opens on what it has: the dull frame fills a later place.
    four = pick_highlights(
        (mirror, room, home, stop, dull), ride_start=_T0, ride_end=_T0 + timedelta(hours=2)
    )
    assert [h.event_id for h in four] == ["s", "d"]


def test_a_picture_taken_standing_still_waits_for_every_moving_one() -> None:
    """The owner's day-5 note (2026-09-07): a viewing deck is not a riding
    film's opening while the road alongside it is still on offer."""
    deck = _window(
        "deck",
        0,
        _analysis(
            "a stationary shot from a wooden viewing platform",
            photogenic_score=0.95,
            highlight_subject="vista",
            stationary="yes",
        ),
    )
    river = _window(
        "river",
        30,
        _analysis(
            "riding beside a river",
            photogenic_score=0.6,
            highlight_subject="water",
            stationary="no",
        ),
    )

    assert [
        h.event_id
        for h in pick_highlights(
            (deck, river), ride_start=_T0, ride_end=_T0 + timedelta(hours=2), count=1
        )
    ] == ["river"]
    # With room for both, the standing picture still comes last in the pass
    # order but keeps its place in ride order.
    both = pick_highlights((deck, river), ride_start=_T0, ride_end=_T0 + timedelta(hours=2))
    assert [h.event_id for h in both] == ["deck", "river"]


def test_nonsense_is_refused() -> None:
    with pytest.raises(ValueError):
        pick_highlights((), ride_start=_T0, ride_end=_T0, count=-1)
    window = _window("a", 0, replace(_analysis("x"), photogenic_score=0.9))
    assert (
        pick_highlights(
            (window,), ride_start=_T0 + timedelta(hours=1), ride_end=_T0 + timedelta(hours=2)
        )
        == ()
    )


def test_photogenic_and_subject_of_a_candidate_with_no_analysis_are_none() -> None:
    bare = JudgedCandidate(event_id="a", start_time=_T0, duration_s=12.0, analysis=None)

    assert photogenic(bare) is None
    assert subject_of(bare) == "none"


def test_photogenic_score_of_exactly_zero_is_used_verbatim_not_treated_as_unset() -> None:
    # The model can answer 0.0; that is a real answer, not "no answer" -- the
    # `is not None` check must not fall through to the text-derived guess,
    # even though the description alone would earn a large bonus.
    flat = _analysis("a glacier and a mountain vista", interest=1.0, photogenic_score=0.0)

    assert photogenic(_window("a", 0, flat)) == 0.0


def test_photogenic_clamps_at_both_extremes_instead_of_overshooting() -> None:
    stacked = _analysis("a glacier, a mountain, and a vista", interest=1.0)
    flat_and_dull = _analysis("a queue of traffic at an intersection", interest=0.0)

    # 0.75 * 1.0 + 0.3 (glacier) would be 1.05 without the clamp.
    assert photogenic(_window("a", 0, stacked)) == 1.0
    # 0.75 * 0.0 - 0.15 (dull) would be negative without the clamp.
    assert photogenic(_window("b", 0, flat_and_dull)) == 0.0


def test_subject_of_trusts_the_models_answer_over_a_contradicting_description() -> None:
    # Only the sentinels "unknown"/"none" fall back to word-guessing; any
    # other named answer wins even when the words would guess differently.
    contradicting = _analysis("a mountain view", highlight_subject="landmark")

    assert subject_of(_window("a", 0, contradicting)) == "landmark"


def test_subject_of_word_guessing_takes_the_first_matching_category_in_order() -> None:
    # "mountain" and "coast" both appear; mountains is checked first.
    both = _analysis("a coastal road below a snow-capped mountain")

    assert subject_of(_window("a", 0, both)) == "mountains"


def test_subject_of_falls_back_to_none_when_no_word_matches() -> None:
    nothing = _analysis("a straight grey road")

    assert subject_of(_window("a", 0, nothing)) == "none"


def test_pick_highlights_count_of_zero_returns_nothing() -> None:
    window = _window("a", 0, _analysis("x", photogenic_score=0.9))

    picked = pick_highlights((window,), ride_start=_T0, ride_end=_T0 + timedelta(hours=1), count=0)

    assert picked == ()


def test_pick_highlights_ride_start_and_ride_end_are_inclusive_boundaries() -> None:
    at_start = _window("start", 0, _analysis("x", photogenic_score=0.9))
    ride_end = _T0 + timedelta(hours=1)
    at_end = JudgedCandidate(
        event_id="end",
        start_time=ride_end,
        duration_s=12.0,
        analysis=_analysis("x", photogenic_score=0.9, highlight_subject="vista"),
    )

    picked = pick_highlights((at_start, at_end), ride_start=_T0, ride_end=ride_end)

    assert {h.event_id for h in picked} == {"start", "end"}


def test_pick_highlights_zero_spread_allows_two_picks_at_the_same_instant() -> None:
    # The default spread would reject two picks this close; spread_s=0 must
    # not exclude same-instant windows (`abs(diff) < 0` is never true).
    a = _window("a", 30, _analysis("x", photogenic_score=0.9, highlight_subject="water"))
    b = _window("b", 30, _analysis("x", photogenic_score=0.85, highlight_subject="mountains"))

    picked = pick_highlights(
        (a, b), ride_start=_T0, ride_end=_T0 + timedelta(hours=1), spread_s=0.0
    )

    assert {h.event_id for h in picked} == {"a", "b"}


def test_pick_highlights_gap_exactly_equal_to_spread_is_allowed_not_excluded() -> None:
    # The spread check is a strict `<`; two picks exactly `spread_s` apart
    # are not "too close".
    early = _window("early", 0, _analysis("x", photogenic_score=0.9, highlight_subject="water"))
    late = _window("late", 20, _analysis("x", photogenic_score=0.85, highlight_subject="mountains"))

    picked = pick_highlights((early, late), ride_start=_T0, ride_end=_T0 + timedelta(hours=1))

    assert {h.event_id for h in picked} == {"early", "late"}


def test_pick_highlights_minimum_boundary_exactly_at_threshold_still_passes() -> None:
    # `highlight.score < minimum` rejects strictly below; exactly at the
    # floor must survive the first two passes, not just the plain-day third.
    at_floor = _window("a", 0, _analysis("x", photogenic_score=0.55))

    picked = pick_highlights(
        (at_floor,),
        ride_start=_T0,
        ride_end=_T0 + timedelta(hours=1),
        count=1,
        scores={"a": 0.0},
    )

    assert [h.event_id for h in picked] == ["a"]


def test_pick_highlights_scores_mapping_breaks_ties_among_equal_photogenic_scores() -> None:
    tied_low_tie = _window("a", 0, _analysis("x", photogenic_score=0.9))
    tied_high_tie = _window("b", 30, _analysis("x", photogenic_score=0.9))

    picked = pick_highlights(
        (tied_low_tie, tied_high_tie),
        ride_start=_T0,
        ride_end=_T0 + timedelta(hours=1),
        count=1,
        scores={"a": 0.0, "b": 1.0},
    )

    assert [h.event_id for h in picked] == ["b"]
