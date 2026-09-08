"""Tests for holding windows by rank and sharing the film out by chapter."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from app.analysis_look import WindowLook
from app.contracts import VideoAnalysis
from app.gap_chapters import GapCharacter
from app.gemini_selection import JudgedCandidate
from app.ride_chapters import RideChapter
from app.story_pacing import (
    LONG_HOLD_S,
    MEDIUM_HOLD_S,
    OPENER_MIN_HOLD_S,
    SHORT_HOLD_S,
    ChapterAllocation,
    StoryPacingError,
    chapter_openers,
    footage_for,
    hold_for,
    paced,
    reallocate_footage_targets,
    select_by_chapter,
)

_T0 = datetime(2026, 5, 1, 6, 0, 0, tzinfo=UTC)


def _judged(
    name: str, *, at_s: float, score: float = 0.7, halt: int | None = None
) -> JudgedCandidate:
    return JudgedCandidate(
        event_id=name,
        start_time=_T0 + timedelta(seconds=at_s),
        duration_s=12.0,
        halt=halt,
        analysis=VideoAnalysis(
            asset_id="asset-1",
            start_offset_s=at_s,
            end_offset_s=at_s + 12.0,
            visual_description="a road",
            road_type="rural road",
            scenery_tags=("sky",),
            weather_visible="clear",
            visual_interest_score=score,
            story_relevance_score=score,
            confidence=0.9,
            analysis_provider="gemini",
        ),
    )


def _chapter(
    start_s: float, end_s: float, character: GapCharacter = GapCharacter.LINK
) -> RideChapter:
    return RideChapter(
        start_time=_T0 + timedelta(seconds=start_s),
        end_time=_T0 + timedelta(seconds=end_s),
        character=character,
        distance_m=1000.0,
        elevation_gain_m=0.0,
        elevation_loss_m=0.0,
        start_elevation_m=None,
        end_elevation_m=None,
        since_departure_s=start_s,
    )


def test_holds_follow_the_models_placing() -> None:
    assert hold_for(1) == LONG_HOLD_S
    assert hold_for(5) == LONG_HOLD_S
    assert hold_for(6) == MEDIUM_HOLD_S
    assert hold_for(None) == SHORT_HOLD_S


def test_paced_candidates_keep_everything_but_their_hold() -> None:
    held = paced((_judged("a", at_s=0.0), _judged("b", at_s=300.0)), ranks={"a": 2})

    assert [c.duration_s for c in held] == [LONG_HOLD_S, SHORT_HOLD_S]
    assert held[0].analysis == _judged("a", at_s=0.0).analysis


def test_each_chapter_gets_its_share_of_the_film() -> None:
    # Chapter one holds two windows, chapter two holds eight, well spaced.
    candidates = tuple(_judged(f"one-{i}", at_s=i * 300.0) for i in range(2)) + tuple(
        _judged(f"two-{i}", at_s=3600.0 + i * 300.0) for i in range(8)
    )
    chapters = (_chapter(0.0, 3600.0), _chapter(3600.0, 7200.0))

    chosen = select_by_chapter(candidates, chapters, ranks=None, footage_target_s=60.0)

    ones = [c for c in chosen if c.startswith("one")]
    twos = [c for c in chosen if c.startswith("two")]
    # 60 s at six seconds each is ten windows; chapter one earns a fifth.
    assert len(ones) == 2 and len(twos) == 8


def test_a_chapter_with_windows_always_gets_at_least_one() -> None:
    candidates = (_judged("lonely", at_s=10.0),) + tuple(
        _judged(f"many-{i}", at_s=3600.0 + i * 300.0) for i in range(30)
    )
    chapters = (_chapter(0.0, 3600.0), _chapter(3600.0, 14000.0))

    chosen = select_by_chapter(candidates, chapters, ranks=None, footage_target_s=60.0)

    assert "lonely" in chosen


def test_a_halt_gets_one_window() -> None:
    candidates = tuple(_judged(f"h-{i}", at_s=i * 300.0, score=0.9, halt=1) for i in range(5))
    chapters = (_chapter(0.0, 1800.0, GapCharacter.HALT),)

    assert len(select_by_chapter(candidates, chapters, ranks=None)) == 1


def test_a_halts_unspent_share_reaches_the_next_chapter() -> None:
    # The halt shares evenly with the leg (ten windows apiece) but can only
    # ever spend one; a plain 50/50 split would leave the leg's target at
    # 40 s -- six of its ten windows -- with the other 34 s thrown away.
    # Handed on, the leg's target reaches 60 s and every window fits.
    halted = tuple(_judged(f"h-{i}", at_s=i * 100.0, score=0.9, halt=1) for i in range(10))
    leg = tuple(_judged(f"leg-{i}", at_s=3600.0 + i * 300.0) for i in range(10))
    chapters = (_chapter(0.0, 1000.0, GapCharacter.HALT), _chapter(1000.0, 10000.0))

    chosen = select_by_chapter(halted + leg, chapters, ranks=None, footage_target_s=80.0)

    assert sum(1 for c in chosen if c.startswith("h-")) == 1
    assert sum(1 for c in chosen if c.startswith("leg-")) == 10


def test_select_by_chapter_can_run_on_a_rank_only_ride() -> None:
    """Gate 7.2 (`app.analysis_tournament`) never buys a `VideoAnalysis`."""
    candidates = tuple(
        JudgedCandidate(
            event_id=f"h-{i}",
            start_time=_T0 + timedelta(seconds=i * 300.0),
            duration_s=12.0,
            analysis=None,
        )
        for i in range(5)
    )
    chapters = (_chapter(0.0, 1800.0),)
    # Worst-first in ride order, best-first in rank: h-4 is the tournament's
    # winner though it is the last thing the camera saw.
    ranks = {c.event_id: rank for rank, c in enumerate(reversed(candidates), start=1)}

    chosen = select_by_chapter(
        candidates, chapters, ranks=ranks, footage_target_s=15.0, requires_analysis=False
    )

    # With no VideoAnalysis to read a floor from, nothing here is excluded
    # on that account; only the target is too small for all five. The rank
    # decides which two survive it (the best two, not the earliest two),
    # and the film still plays them back in ride order.
    assert chosen == ("h-3", "h-4")


def test_a_chapter_without_windows_is_skipped_not_an_error() -> None:
    candidates = (_judged("a", at_s=10.0),)
    chapters = (_chapter(0.0, 100.0), _chapter(100.0, 200.0))

    assert select_by_chapter(candidates, chapters, ranks=None) == ("a",)


def test_bad_inputs_are_refused() -> None:
    with pytest.raises(StoryPacingError):
        select_by_chapter(
            (_judged("a", at_s=0.0),), (_chapter(0.0, 10.0),), ranks=None, footage_target_s=0.0
        )
    with pytest.raises(StoryPacingError):
        select_by_chapter((_judged("a", at_s=0.0),), (), ranks=None)


def test_footage_is_held_for_its_pace_and_three_alike_are_broken_up() -> None:
    candidates = tuple(_judged(f"w{i}", at_s=i * 300.0) for i in range(4))

    footage = footage_for(("w0", "w1", "w2", "w3"), candidates, ranks=None)

    holds = [f.duration_s for f in footage]
    # Unranked and alike: the best fifth (one) gets the long hold, the rest
    # the short one, and a run of three shorts is broken up in the middle.
    assert holds.count(LONG_HOLD_S) == 1
    assert MEDIUM_HOLD_S in holds
    assert not any(a == b == c for a, b, c in zip(holds, holds[1:], holds[2:], strict=False))
    assert [f.event_id for f in footage] == ["w0", "w1", "w2", "w3"]


def test_a_long_hold_never_exceeds_the_window() -> None:
    short = JudgedCandidate(event_id="s", start_time=_T0, duration_s=4.0, analysis=None)
    assert paced((short,), ranks={"s": 1})[0].duration_s == 4.0


def test_the_long_hold_goes_to_the_best_fifth_of_the_chosen() -> None:
    candidates = tuple(_judged(f"w{i}", at_s=i * 300.0, score=0.5 + i * 0.01) for i in range(10))
    ranks = {f"w{i}": 10 - i for i in range(10)}  # w9 is the model's first

    footage = footage_for(tuple(f"w{i}" for i in range(10)), candidates, ranks=ranks)

    by_id = {f.event_id: f.duration_s for f in footage}
    assert by_id["w9"] == LONG_HOLD_S and by_id["w8"] == LONG_HOLD_S
    assert by_id["w0"] == MEDIUM_HOLD_S


# -- reallocate_footage_targets: sending a chapter's unspent share on to the rest --


def test_within_capacity_each_chapter_just_gets_its_share() -> None:
    targets = reallocate_footage_targets(
        (
            ChapterAllocation("a", weight=1.0, capacity_s=100.0),
            ChapterAllocation("b", weight=3.0, capacity_s=100.0),
        ),
        footage_target_s=40.0,
    )

    assert targets == pytest.approx({"a": 10.0, "b": 30.0})


def test_one_capped_chapter_hands_its_rest_to_the_only_other_one() -> None:
    # "a" would earn 20 s but can only ever spend 6 (one short window);
    # the 14 s it cannot use goes to "b".
    targets = reallocate_footage_targets(
        (
            ChapterAllocation("a", weight=1.0, capacity_s=6.0),
            ChapterAllocation("b", weight=1.0, capacity_s=100.0),
        ),
        footage_target_s=40.0,
    )

    assert targets == pytest.approx({"a": 6.0, "b": 34.0})


def test_overflow_splits_by_weight_among_the_chapters_with_room() -> None:
    targets = reallocate_footage_targets(
        (
            ChapterAllocation("a", weight=2.0, capacity_s=6.0),
            ChapterAllocation("b", weight=1.0, capacity_s=100.0),
            ChapterAllocation("c", weight=1.0, capacity_s=100.0),
        ),
        footage_target_s=40.0,
    )

    # "a" earned 20, spends 6, hands 14 to "b" and "c" 1:1 by weight.
    assert targets == pytest.approx({"a": 6.0, "b": 17.0, "c": 17.0})
    assert sum(targets.values()) == pytest.approx(40.0)


def test_a_second_chapter_can_be_capped_by_what_it_is_handed() -> None:
    # "a" is capped first; what it hands to "b" and "c" is enough to push
    # "b" over its own small capacity too, so a second round hands the
    # rest on to "c" alone.
    targets = reallocate_footage_targets(
        (
            ChapterAllocation("a", weight=6.0, capacity_s=6.0),
            ChapterAllocation("b", weight=1.0, capacity_s=8.0),
            ChapterAllocation("c", weight=1.0, capacity_s=100.0),
        ),
        footage_target_s=48.0,
    )

    assert targets["a"] == pytest.approx(6.0)
    assert targets["b"] == pytest.approx(8.0)
    assert sum(targets.values()) == pytest.approx(48.0)


def test_a_remainder_with_nowhere_to_go_is_simply_unspent() -> None:
    # Every chapter is capped well under an even share; the target can't
    # all be spent, but no chapter is ever asked for more than it has.
    targets = reallocate_footage_targets(
        (
            ChapterAllocation("a", weight=1.0, capacity_s=6.0),
            ChapterAllocation("b", weight=1.0, capacity_s=6.0),
        ),
        footage_target_s=40.0,
    )

    assert targets == {"a": 6.0, "b": 6.0}
    assert sum(targets.values()) < 40.0


def test_all_zero_weight_chapters_split_evenly() -> None:
    targets = reallocate_footage_targets(
        (
            ChapterAllocation("a", weight=0.0, capacity_s=100.0),
            ChapterAllocation("b", weight=0.0, capacity_s=100.0),
        ),
        footage_target_s=40.0,
    )

    assert targets == pytest.approx({"a": 20.0, "b": 20.0})


def test_all_zero_weight_overflow_also_splits_evenly() -> None:
    targets = reallocate_footage_targets(
        (
            ChapterAllocation("a", weight=0.0, capacity_s=6.0),
            ChapterAllocation("b", weight=0.0, capacity_s=100.0),
            ChapterAllocation("c", weight=0.0, capacity_s=100.0),
        ),
        footage_target_s=30.0,
    )

    assert targets == pytest.approx({"a": 6.0, "b": 12.0, "c": 12.0})


def test_a_thin_chapter_still_gets_the_floor_if_it_can_use_it() -> None:
    # Capacities generous enough that no capping ever kicks in: this
    # isolates the floor from the overflow round entirely.
    targets = reallocate_footage_targets(
        (
            ChapterAllocation("a", weight=0.01, capacity_s=1000.0),
            ChapterAllocation("b", weight=99.99, capacity_s=1000.0),
        ),
        footage_target_s=240.0,
        floor_s=6.0,
    )

    assert targets["a"] == pytest.approx(6.0)
    assert targets["b"] == pytest.approx(239.976)


def test_a_single_chapter_gets_all_it_can_hold() -> None:
    assert reallocate_footage_targets(
        (ChapterAllocation("a", weight=1.0, capacity_s=100.0),), footage_target_s=40.0
    ) == pytest.approx({"a": 40.0})
    assert reallocate_footage_targets(
        (ChapterAllocation("a", weight=1.0, capacity_s=10.0),), footage_target_s=40.0
    ) == pytest.approx({"a": 10.0})


def test_reallocation_never_exceeds_a_chapters_capacity() -> None:
    targets = reallocate_footage_targets(
        (
            ChapterAllocation("a", weight=1.0, capacity_s=6.0),
            ChapterAllocation("b", weight=1.0, capacity_s=8.0),
            ChapterAllocation("c", weight=1.0, capacity_s=6.0),
        ),
        footage_target_s=60.0,
    )

    for chapter_id, capacity in (("a", 6.0), ("b", 8.0), ("c", 6.0)):
        assert targets[chapter_id] <= capacity + 1e-9


def test_reallocation_bad_inputs_are_refused() -> None:
    good = (ChapterAllocation("a", weight=1.0, capacity_s=10.0),)
    with pytest.raises(StoryPacingError):
        reallocate_footage_targets(good, footage_target_s=0.0)
    with pytest.raises(StoryPacingError):
        reallocate_footage_targets(good, footage_target_s=40.0, floor_s=0.0)
    with pytest.raises(StoryPacingError):
        reallocate_footage_targets((), footage_target_s=40.0)
    with pytest.raises(StoryPacingError):
        reallocate_footage_targets(
            (
                ChapterAllocation("a", weight=1.0, capacity_s=10.0),
                ChapterAllocation("a", weight=1.0, capacity_s=10.0),
            ),
            footage_target_s=40.0,
        )
    with pytest.raises(StoryPacingError):
        reallocate_footage_targets(
            (ChapterAllocation("", weight=1.0, capacity_s=10.0),), footage_target_s=40.0
        )
    with pytest.raises(StoryPacingError):
        reallocate_footage_targets(
            (ChapterAllocation("a", weight=-1.0, capacity_s=10.0),), footage_target_s=40.0
        )
    with pytest.raises(StoryPacingError):
        reallocate_footage_targets(
            (ChapterAllocation("a", weight=1.0, capacity_s=-1.0),), footage_target_s=40.0
        )


# --- E-2: holds from motion, the half that moves, the opener's floor ----------------------------


def _look(motion: float, series: tuple[float, ...] = ()) -> WindowLook:
    return WindowLook(
        luma=100.0, chroma_u=128.0, chroma_v=128.0, motion=motion, motion_series=series
    )


def test_with_looks_the_tiers_become_ranges_placed_by_motion() -> None:
    candidates = tuple(_judged(f"w{i}", at_s=100.0 * i) for i in range(6))
    ranks = {f"w{i}": i + 1 for i in range(6)}
    # Six chosen: the best fifth is two, w0 and w1 -> long tier; calm w0, busy w1.
    looks = {
        "w0": _look(0.0),
        "w1": _look(40.0),
        "w2": _look(10.0),
        "w3": _look(30.0),
        "w4": _look(20.0),
        "w5": _look(0.0),
    }

    footage = footage_for(tuple(f"w{i}" for i in range(6)), candidates, ranks=ranks, looks=looks)

    holds = {f.event_id: f.duration_s for f in footage}
    assert holds["w0"] == 8.0 and holds["w1"] == 10.0, "the long tier spans 8-10 s by motion"
    assert all(5.0 <= holds[f"w{i}"] <= 7.0 for i in range(2, 6)), "ranked rest: 5-7 s"
    assert holds["w2"] < holds["w3"], "the busier window holds longer"


def test_without_a_look_for_every_window_the_fixed_holds_stand() -> None:
    candidates = tuple(_judged(f"w{i}", at_s=100.0 * i) for i in range(3))
    looks = {"w0": _look(1.0)}  # w1, w2 unmeasured

    footage = footage_for(("w0", "w1", "w2"), candidates, ranks=None, looks=looks)

    assert all(f.source_offset_s == 0.0 for f in footage)
    assert sorted(f.duration_s for f in footage) == [6.0, 6.0, 10.0], (
        "the old tiers: one long, two short"
    )


def test_the_half_that_moves_more_is_the_half_that_plays() -> None:
    candidates = (_judged("calm-then-busy", at_s=0.0), _judged("busy-then-calm", at_s=100.0))
    looks = {
        "calm-then-busy": _look(5.0, series=(0, 0, 0, 0, 0, 10, 10, 10, 10, 10, 10)),
        "busy-then-calm": _look(5.0, series=(10, 10, 10, 10, 10, 10, 0, 0, 0, 0, 0)),
    }

    footage = {
        f.event_id: f
        for f in footage_for(
            ("calm-then-busy", "busy-then-calm"), candidates, ranks=None, looks=looks
        )
    }

    late = footage["calm-then-busy"]
    assert late.source_offset_s == 12.0 - late.duration_s, "the cut starts where the motion is"
    assert late.start_time == _T0 + timedelta(seconds=late.source_offset_s)
    early = footage["busy-then-calm"]
    assert early.source_offset_s == 0.0


def test_an_opener_holds_long_enough_to_carry_its_title() -> None:
    candidates = tuple(_judged(f"w{i}", at_s=100.0 * i) for i in range(3))
    looks = {f"w{i}": _look(0.0) for i in range(3)}  # everything calm: the short tier is 3-4 s

    plain = {
        f.event_id: f.duration_s
        for f in footage_for(("w0", "w1", "w2"), candidates, ranks=None, looks=looks)
    }
    opened = {
        f.event_id: f.duration_s
        for f in footage_for(
            ("w0", "w1", "w2"), candidates, ranks=None, looks=looks, openers={"w1"}
        )
    }

    assert plain["w1"] < OPENER_MIN_HOLD_S and plain["w2"] < OPENER_MIN_HOLD_S
    assert opened["w1"] == OPENER_MIN_HOLD_S, "the opener is lifted to the floor"
    assert opened["w2"] == plain["w2"], "a window that opens nothing keeps its hold"


def test_chapter_openers_are_the_first_chosen_window_of_each_chapter() -> None:
    candidates = tuple(_judged(f"w{i}", at_s=600.0 * i) for i in range(6))
    chapters = (_chapter(0.0, 1500.0), _chapter(1500.0, 3600.0))

    openers = chapter_openers(("w4", "w1", "w3", "w0"), candidates, chapters)

    assert openers == frozenset({"w0", "w3"})


def test_with_looks_the_same_target_takes_more_windows() -> None:
    """Counted at the middle of its range, a window is shorter, so the target needs more of them."""
    candidates = tuple(_judged(f"w{i}", at_s=400.0 * i) for i in range(20))
    chapters = (_chapter(0.0, 8000.0),)
    # Distinct looks (brightness climbs), so the look-alike rule stays out of it.
    looks = {
        f"w{i}": WindowLook(
            luma=float(i % 2) * 200.0,  # alternate dark and bright: never look-alike neighbours
            chroma_u=128.0,
            chroma_v=128.0,
            motion=float(i),
            motion_series=(),
        )
        for i in range(20)
    }

    fixed = select_by_chapter(candidates, chapters, ranks=None, footage_target_s=60.0)
    by_motion = select_by_chapter(
        candidates, chapters, ranks=None, footage_target_s=60.0, looks=looks
    )

    assert len(by_motion) > len(fixed)


def test_a_short_day_is_told_slower_not_cut_short() -> None:
    candidates = tuple(_judged(f"w{i}", at_s=100.0 * i) for i in range(3))
    looks = {f"w{i}": _look(0.0) for i in range(3)}  # calm: every hold at its range's bottom

    plain = {
        f.event_id: f.duration_s
        for f in footage_for(("w0", "w1", "w2"), candidates, ranks=None, looks=looks)
    }
    raised = {
        f.event_id: f.duration_s
        for f in footage_for(
            ("w0", "w1", "w2"), candidates, ranks=None, looks=looks, footage_target_s=60.0
        )
    }

    assert sum(plain.values()) < 60.0
    assert all(raised[e] >= plain[e] for e in plain), "no hold gets shorter"
    assert raised["w0"] == 10.0, "the long-tier window reaches the top of its range"
    assert raised["w1"] == 4.0 and raised["w2"] == 4.0, (
        "short-tier windows reach theirs, and no further"
    )
    assert sum(raised.values()) < 60.0, "the ranges bound what a short day can be stretched to"


def test_a_day_that_meets_its_target_keeps_its_motion_placed_holds() -> None:
    candidates = tuple(_judged(f"w{i}", at_s=100.0 * i) for i in range(3))
    looks = {"w0": _look(0.0), "w1": _look(5.0), "w2": _look(10.0)}

    plain = footage_for(("w0", "w1", "w2"), candidates, ranks=None, looks=looks)
    same = footage_for(
        ("w0", "w1", "w2"), candidates, ranks=None, looks=looks, footage_target_s=10.0
    )

    assert [f.duration_s for f in same] == [f.duration_s for f in plain]


def test_a_partial_shortfall_is_shared_in_proportion_to_headroom() -> None:
    candidates = tuple(_judged(f"w{i}", at_s=100.0 * i) for i in range(3))
    looks = {f"w{i}": _look(0.0) for i in range(3)}
    plain = {
        f.event_id: f.duration_s
        for f in footage_for(("w0", "w1", "w2"), candidates, ranks=None, looks=looks)
    }
    # Equal motion places each hold mid-range: 9 + 3.5 + 3.5 = 16; tops 10 + 4 + 4 = 18.
    # Ask for 17: half the headroom.
    raised = {
        f.event_id: f.duration_s
        for f in footage_for(
            ("w0", "w1", "w2"), candidates, ranks=None, looks=looks, footage_target_s=17.0
        )
    }

    assert raised["w0"] == pytest.approx(plain["w0"] + 0.5)
    assert raised["w1"] == pytest.approx(plain["w1"] + 0.25)
    assert sum(raised.values()) == pytest.approx(17.0)


# --- the shots the film always carries ---------------------------------------


def test_a_fixed_shot_is_held_from_its_own_start_for_its_own_length() -> None:
    """The still seconds before the move are the picture; no half is chosen."""
    from app.fixed_shots import FIXED_SHOT_HOLD_S

    leaving = _judged("leaving", at_s=0.0)
    road = _judged("road", at_s=600.0)
    looks = {
        "leaving": WindowLook(
            luma=0.5, chroma_u=0.5, chroma_v=0.5, motion=0.9, motion_series=(0.1,) * 6 + (0.9,) * 6
        ),
        "road": WindowLook(luma=0.5, chroma_u=0.5, chroma_v=0.5, motion=0.5),
    }

    footage = footage_for(
        ("leaving", "road"), (leaving, road), ranks=None, looks=looks, fixed={"leaving"}
    )

    first = footage[0]
    assert first.event_id == "leaving"
    assert first.source_offset_s == 0.0
    assert (first.end_time - first.start_time).total_seconds() == FIXED_SHOT_HOLD_S


def test_select_by_chapter_passes_the_required_windows_to_their_own_chapter() -> None:
    weak = _judged("leaving", at_s=10.0, score=0.1)
    strong = _judged("road", at_s=3000.0, score=0.9)
    chapters = (_chapter(0.0, 1800.0), _chapter(1800.0, 3600.0))

    chosen = select_by_chapter(
        (weak, strong), chapters, footage_target_s=12.0, required={"leaving"}
    )

    assert "leaving" in chosen
    assert "road" in chosen


def test_legs_keep_clear_of_each_others_windows_across_the_boundary() -> None:
    """A fixed shot straddling the boundary and the next leg's first window never overlap."""
    leaving = _judged("leaving", at_s=1797.0, score=0.5)
    straddled = _judged("straddled", at_s=1802.0, score=0.9)
    later = _judged("later", at_s=2400.0, score=0.6)
    chapters = (_chapter(0.0, 1800.0), _chapter(1800.0, 3600.0))

    chosen = select_by_chapter(
        (leaving, straddled, later), chapters, footage_target_s=30.0, required={"leaving"}
    )

    assert "leaving" in chosen
    assert "straddled" not in chosen
    assert "later" in chosen


def test_the_fixed_shots_take_their_time_off_the_top_of_the_target() -> None:
    """Many fixed shots do not make a longer film; the ordinary picks give way."""
    windows = tuple(_judged(f"w{i}", at_s=i * 300.0, score=0.8) for i in range(24))
    chapters = (_chapter(0.0, 3600.0), _chapter(3600.0, 7200.0))
    fixed = {f"w{i}" for i in range(0, 24, 3)}  # eight fixed shots

    plain = select_by_chapter(windows, chapters, footage_target_s=120.0)
    with_fixed = select_by_chapter(windows, chapters, footage_target_s=120.0, required=fixed)

    by_id = {c.event_id: c for c in windows}
    total_plain = sum(min(by_id[e].duration_s, 6.0) for e in plain)
    total_fixed = sum(min(by_id[e].duration_s, 6.0) for e in with_fixed)
    assert fixed <= set(with_fixed)
    assert total_fixed <= total_plain + 6.0


def test_no_two_cuts_share_a_second_of_the_ride() -> None:
    """A cut reaching into the next window's start is shortened; a sliver is dropped."""
    from app.story_pacing import _without_overlaps
    from app.story_timeline import TimelineFootage

    a = TimelineFootage("a", _T0, _T0 + timedelta(seconds=10), 0.0)
    b = TimelineFootage("b", _T0 + timedelta(seconds=6), _T0 + timedelta(seconds=14), 0.0)
    c = TimelineFootage("c", _T0 + timedelta(seconds=15), _T0 + timedelta(seconds=23), 0.0)
    sliver = TimelineFootage("s", _T0 + timedelta(seconds=22), _T0 + timedelta(seconds=30), 0.0)
    d = TimelineFootage("d", _T0 + timedelta(seconds=23), _T0 + timedelta(seconds=31), 0.0)

    kept = _without_overlaps([d, sliver, c, b, a])

    assert [f.event_id for f in kept] == ["a", "b", "c", "d"]
    assert kept[0].end_time == b.start_time
    assert kept[1].end_time == b.end_time  # b ends before c begins: untouched
    assert all(x.end_time <= y.start_time for x, y in zip(kept, kept[1:], strict=False))
