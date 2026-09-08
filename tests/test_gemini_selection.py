"""Synthetic-fixture tests for turning Gemini's judgement into a selection."""

from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta

import pytest

from app.contracts import VideoAnalysis
from app.gemini_selection import (
    DEFAULT_MINIMUM_SEPARATION_S,
    REASON_ENOUGH_FOOTAGE,
    REASON_FIXED_SHOT,
    REASON_LOW_CONFIDENCE,
    REASON_LOW_SCORE,
    REASON_NO_ANALYSIS,
    REASON_PRIVATE_RESIDENCE,
    REASON_RIDER_IN_FRAME,
    REASON_SAME_HALT,
    REASON_SELECTED,
    REASON_STANDING,
    REASON_TOO_CLOSE,
    GeminiSelectionError,
    JudgedCandidate,
    select_judged_candidates,
)

_START = datetime(2026, 5, 1, 9, 0, 0, tzinfo=UTC)


def _analysis(
    *,
    interest: float = 0.8,
    story: float = 0.8,
    confidence: float = 0.9,
    description: str = "A road through trees",
) -> VideoAnalysis:
    return VideoAnalysis(
        asset_id="asset-synthetic-1",
        start_offset_s=0.0,
        end_offset_s=12.0,
        visual_description=description,
        road_type="mountain road",
        scenery_tags=("trees", "sky"),
        weather_visible="clear",
        visual_interest_score=interest,
        story_relevance_score=story,
        confidence=confidence,
        analysis_provider="gemini",
    )


def _candidate(
    index: int,
    *,
    minutes: float | None = None,
    duration_s: float = 30.0,
    analysis: VideoAnalysis | None = ...,  # type: ignore[assignment]
) -> JudgedCandidate:
    return JudgedCandidate(
        event_id=f"evt_{index}",
        start_time=_START + timedelta(minutes=index * 10 if minutes is None else minutes),
        duration_s=duration_s,
        analysis=_analysis() if analysis is ... else analysis,
    )


def _reason(selection, event_id: str) -> str:
    return next(v.reason for v in selection.verdicts if v.event_id == event_id)


# --- what the scores mean ---------------------------------------------------


def test_story_relevance_outweighs_a_pretty_but_irrelevant_clip() -> None:
    """A striking shot of a car park is a showreel, not a journey."""
    pretty = _candidate(0, analysis=_analysis(interest=1.0, story=0.1))
    relevant = _candidate(1, analysis=_analysis(interest=0.5, story=0.9))

    assert relevant.score() > pretty.score()


def test_the_weights_are_adjustable_not_buried() -> None:
    pretty = _candidate(0, analysis=_analysis(interest=1.0, story=0.1))

    story_led = pretty.score(interest_weight=0.4, story_weight=0.6)
    looks_led = pretty.score(interest_weight=0.9, story_weight=0.1)

    assert looks_led > story_led


def test_a_candidate_nobody_judged_scores_nothing() -> None:
    assert _candidate(0, analysis=None).score() == 0.0


# --- who gets in ------------------------------------------------------------


def test_the_strongest_candidates_are_taken() -> None:
    candidates = (
        _candidate(0, analysis=_analysis(interest=0.9, story=0.9)),
        _candidate(1, analysis=_analysis(interest=0.2, story=0.2)),
        _candidate(2, analysis=_analysis(interest=0.85, story=0.85)),
    )

    selection = select_judged_candidates(candidates)

    assert set(selection.selected_event_ids) == {"evt_0", "evt_2"}
    assert _reason(selection, "evt_1") == REASON_LOW_SCORE


def test_an_unsure_verdict_is_no_verdict() -> None:
    """A confident middling answer beats an unsure glowing one."""
    candidates = (
        _candidate(0, analysis=_analysis(interest=1.0, story=1.0, confidence=0.1)),
        _candidate(1, analysis=_analysis(interest=0.6, story=0.6, confidence=0.9)),
    )

    selection = select_judged_candidates(candidates)

    assert selection.selected_event_ids == ("evt_1",)
    assert _reason(selection, "evt_0") == REASON_LOW_CONFIDENCE


def test_a_candidate_that_was_never_analysed_cannot_be_selected() -> None:
    candidates = (_candidate(0, analysis=None), _candidate(1))

    selection = select_judged_candidates(candidates)

    assert _reason(selection, "evt_0") == REASON_NO_ANALYSIS
    assert "evt_0" not in selection.selected_event_ids


# --- spacing ----------------------------------------------------------------


def test_clips_from_one_good_minute_do_not_become_the_film() -> None:
    """The stronger clip already speaks for that stretch of road."""
    strong = _candidate(0, minutes=0, analysis=_analysis(interest=0.95, story=0.95))
    beside_it = _candidate(1, minutes=0.6, analysis=_analysis(interest=0.9, story=0.9))
    far_away = _candidate(2, minutes=60, analysis=_analysis(interest=0.9, story=0.9))

    selection = select_judged_candidates((strong, beside_it, far_away))

    assert set(selection.selected_event_ids) == {"evt_0", "evt_2"}
    assert _reason(selection, "evt_1") == REASON_TOO_CLOSE


def test_separation_is_measured_between_windows_not_their_starts() -> None:
    """Two long clips can start far apart and still be adjacent on the road."""
    first = _candidate(0, minutes=0, duration_s=100.0)
    second = _candidate(1, minutes=2, duration_s=100.0)

    selection = select_judged_candidates(
        (first, second), minimum_separation_s=DEFAULT_MINIMUM_SEPARATION_S
    )

    assert len(selection.selected_event_ids) == 1


def test_spacing_can_be_switched_off() -> None:
    candidates = (_candidate(0, minutes=0), _candidate(1, minutes=0.5))

    selection = select_judged_candidates(candidates, minimum_separation_s=0.0)

    assert len(selection.selected_event_ids) == 2


# --- how much ---------------------------------------------------------------


def test_selection_stops_once_there_is_enough_footage() -> None:
    candidates = tuple(_candidate(index) for index in range(20))

    selection = select_judged_candidates(candidates, footage_target_s=90.0)

    assert selection.footage_duration_s >= 90.0
    assert any(v.reason == REASON_ENOUGH_FOOTAGE for v in selection.verdicts)


def test_a_thin_ride_makes_a_shorter_film_rather_than_a_padded_one() -> None:
    """The target is an aim, not a quota."""
    candidates = (_candidate(0), _candidate(1))

    selection = select_judged_candidates(candidates, footage_target_s=600.0)

    assert selection.footage_duration_s == pytest.approx(60.0)
    assert len(selection.selected_event_ids) == 2


# --- the report -------------------------------------------------------------


def test_every_candidate_gets_a_verdict_in_ride_order() -> None:
    candidates = (_candidate(2), _candidate(0), _candidate(1))

    selection = select_judged_candidates(candidates)

    assert [v.event_id for v in selection.verdicts] == ["evt_0", "evt_1", "evt_2"]
    assert all(v.reason for v in selection.verdicts)


def test_the_report_never_quotes_the_model_or_names_an_event() -> None:
    candidates = (
        _candidate(0, analysis=_analysis(description="A red car with plate XYZ 123")),
        _candidate(1, analysis=None),
    )

    payload = select_judged_candidates(candidates).to_dict()
    serialized = json.dumps(payload, ensure_ascii=False)

    assert payload["candidate_count"] == 2
    for forbidden in ("evt_", "asset-", "XYZ 123", "A red car", "mountain road"):
        assert forbidden not in serialized
    assert set(payload["verdicts"][0]) == {"selected", "reason", "score"}


def test_the_reasons_are_counted_for_a_reader() -> None:
    candidates = (
        _candidate(0),
        _candidate(1, analysis=None),
        _candidate(2, analysis=_analysis(interest=0.1, story=0.1)),
    )

    counts = select_judged_candidates(candidates).to_dict()["reasons"]

    assert counts[REASON_SELECTED] == 1
    assert counts[REASON_NO_ANALYSIS] == 1
    assert counts[REASON_LOW_SCORE] == 1


# --- refusals ---------------------------------------------------------------


def test_an_empty_or_repeating_candidate_list_is_refused() -> None:
    with pytest.raises(GeminiSelectionError, match="no candidates"):
        select_judged_candidates(())
    with pytest.raises(GeminiSelectionError, match="must not repeat"):
        select_judged_candidates((_candidate(0), _candidate(0)))


def test_impossible_settings_are_refused() -> None:
    with pytest.raises(GeminiSelectionError, match="separation cannot be negative"):
        select_judged_candidates((_candidate(0),), minimum_separation_s=-1.0)
    with pytest.raises(GeminiSelectionError, match="positive footage target"):
        select_judged_candidates((_candidate(0),), footage_target_s=0.0)
    with pytest.raises(GeminiSelectionError, match="weights must add up"):
        _candidate(0).score(interest_weight=0.0, story_weight=0.0)


def test_a_candidate_needs_an_event_and_a_real_window() -> None:
    with pytest.raises(ValueError, match="needs its event"):
        JudgedCandidate(event_id="", start_time=_START, duration_s=30.0, analysis=None)
    with pytest.raises(ValueError, match="positive duration"):
        JudgedCandidate(event_id="e", start_time=_START, duration_s=0.0, analysis=None)
    with pytest.raises(ValueError, match="timezone-aware"):
        JudgedCandidate(
            event_id="e",
            start_time=datetime(2026, 5, 1, 9, 0, 0),
            duration_s=30.0,
            analysis=None,
        )


def test_among_windows_scored_alike_the_one_holding_a_turn_goes_first() -> None:
    from app.gemini_selection import window_moments
    from app.gps.turns import SharpTurn

    plain = _candidate(1, minutes=0.0)
    corner = _candidate(2, minutes=10.0)
    turn = SharpTurn(
        corner.start_time + timedelta(seconds=4), corner.start_time + timedelta(seconds=8), 110.0
    )
    moments = window_moments((plain, corner), (turn,))
    assert moments == {"evt_2": 110.0}

    without = select_judged_candidates((plain, corner), footage_target_s=6.0)
    with_moments = select_judged_candidates((plain, corner), footage_target_s=6.0, moments=moments)

    assert without.selected_event_ids[0] == "evt_1", "the earlier window wins a plain tie"
    assert with_moments.selected_event_ids[0] == "evt_2"


# --- the rider is not the picture -------------------------------------------


def test_a_window_the_rider_fills_is_out_whatever_it_scored() -> None:
    """The owner's rule: a face in the mirror is not a view of the road."""
    from dataclasses import replace

    mirror = _candidate(
        0,
        analysis=_analysis(interest=1.0, story=1.0, description="the mirror reflecting the rider"),
    )
    asked = _candidate(
        1, analysis=replace(_analysis(interest=1.0, story=1.0), rider_visible="large")
    )
    glove = _candidate(
        2, analysis=replace(_analysis(description="a glove at the edge"), rider_visible="small")
    )
    road = _candidate(3)

    selection = select_judged_candidates((mirror, asked, glove, road))

    assert _reason(selection, "evt_0") == REASON_RIDER_IN_FRAME
    assert _reason(selection, "evt_1") == REASON_RIDER_IN_FRAME
    assert _reason(selection, "evt_2") == REASON_SELECTED
    assert _reason(selection, "evt_3") == REASON_SELECTED


# --- the shots the film always carries ---------------------------------------


def test_a_required_window_is_kept_whatever_it_scored() -> None:
    """A departure that scored 0.3 is still the departure (app.fixed_shots)."""
    leaving = _candidate(0, analysis=_analysis(interest=0.2, story=0.2, confidence=0.3))
    road = _candidate(1)

    selection = select_judged_candidates((leaving, road), required={"evt_0"})

    assert _reason(selection, "evt_0") == REASON_FIXED_SHOT
    assert "evt_0" in selection.selected_event_ids
    assert _reason(selection, "evt_1") == REASON_SELECTED


def test_a_required_window_still_needs_a_judgement_but_may_show_the_rider() -> None:
    """The owner (2026-09-07): the moment matters more than the rider in the mirror."""
    from dataclasses import replace

    unjudged = _candidate(0, analysis=None)
    mirror = _candidate(1, analysis=replace(_analysis(), rider_visible="large"))

    selection = select_judged_candidates(
        (unjudged, mirror, _candidate(2)), required={"evt_0", "evt_1"}
    )

    assert _reason(selection, "evt_0") == REASON_NO_ANALYSIS
    assert _reason(selection, "evt_1") == REASON_FIXED_SHOT


def test_a_required_window_counts_toward_the_target_and_keeps_its_neighbours_apart() -> None:
    leaving = _candidate(0, duration_s=30.0)
    too_close = _candidate(0, minutes=1.0, duration_s=30.0)
    later = _candidate(2, duration_s=30.0)
    later = later.__class__(
        event_id="evt_later", start_time=later.start_time, duration_s=30.0, analysis=later.analysis
    )
    too_close = too_close.__class__(
        event_id="evt_close",
        start_time=too_close.start_time,
        duration_s=30.0,
        analysis=too_close.analysis,
    )

    selection = select_judged_candidates(
        (leaving, too_close, later), required={"evt_0"}, footage_target_s=90.0
    )

    assert _reason(selection, "evt_0") == REASON_FIXED_SHOT
    assert _reason(selection, "evt_close") == REASON_TOO_CLOSE
    assert _reason(selection, "evt_later") == REASON_SELECTED
    assert selection.footage_duration_s == 60.0


def test_a_window_too_close_to_one_already_in_the_film_elsewhere_is_out() -> None:
    """The previous leg's last window and this leg's first must not overlap."""
    elsewhere = _candidate(0)
    too_close = _candidate(1, minutes=0.5)
    far = _candidate(3)

    selection = select_judged_candidates((too_close, far), avoid=(elsewhere,))

    assert _reason(selection, "evt_1") == REASON_TOO_CLOSE
    assert _reason(selection, "evt_3") == REASON_SELECTED
    assert selection.footage_duration_s == far.duration_s


def test_a_window_at_a_private_residence_is_out_even_as_a_fixed_shot() -> None:
    """The owner's correction (2026-09-07): a car park is fine; a home's driveway never is."""
    home = _candidate(0, analysis=_analysis(description="rolling down the driveway of a house"))
    leaving = _candidate(1, analysis=_analysis(description="leaving the car park at dawn"))
    road = _candidate(2)

    selection = select_judged_candidates(
        (home, leaving, road), required={"evt_0", "evt_1"}, parked_allowed={"evt_0", "evt_1"}
    )

    assert _reason(selection, "evt_0") == REASON_PRIVATE_RESIDENCE
    assert _reason(selection, "evt_1") == REASON_FIXED_SHOT
    assert _reason(selection, "evt_2") == REASON_SELECTED


def test_a_window_where_the_bike_never_moved_is_out_unless_allowed() -> None:
    from dataclasses import replace

    waiting = _candidate(0, analysis=replace(_analysis(), stationary="yes"))
    leaving = _candidate(1, analysis=replace(_analysis(), stationary="yes"))
    riding = _candidate(2, analysis=replace(_analysis(), stationary="no"))

    selection = select_judged_candidates(
        (waiting, leaving, riding), required={"evt_1"}, parked_allowed={"evt_1"}
    )

    assert _reason(selection, "evt_0") == REASON_STANDING
    assert _reason(selection, "evt_1") == REASON_FIXED_SHOT
    assert _reason(selection, "evt_2") == REASON_SELECTED


# --- Gate 7.2's rank-only path (requires_analysis=False) --------------------


def test_rank_only_selection_does_not_exclude_candidates_nobody_analysed() -> None:
    """A tournament never buys a `VideoAnalysis`; that alone must not be why nothing is picked."""
    candidates = (_candidate(0, analysis=None), _candidate(1, analysis=None))
    ranks = {"evt_0": 1, "evt_1": 2}

    selection = select_judged_candidates(candidates, ranks=ranks, requires_analysis=False)

    assert set(selection.selected_event_ids) == {"evt_0", "evt_1"}
    assert _reason(selection, "evt_0") == REASON_SELECTED


def test_rank_only_selection_orders_ties_by_rank_since_no_score_can_break_them() -> None:
    candidates = (
        _candidate(0, analysis=None),
        _candidate(1, analysis=None),
        _candidate(2, analysis=None),
    )
    ranks = {"evt_0": 3, "evt_1": 1, "evt_2": 2}

    selection = select_judged_candidates(
        candidates,
        ranks=ranks,
        requires_analysis=False,
        footage_target_s=candidates[0].duration_s,
    )

    # Every score is 0.0 with no analysis to read, so all three candidates
    # tie; the rank is the only thing left to choose among them, and the
    # footage target is set to admit exactly one.
    assert selection.selected_event_ids == ("evt_1",)


def test_rank_only_selection_still_respects_spacing_and_one_window_per_halt() -> None:
    same_halt_first = JudgedCandidate(
        event_id="evt_0", start_time=_START, duration_s=30.0, analysis=None, halt=1
    )
    same_halt_second = JudgedCandidate(
        event_id="evt_1",
        start_time=_START + timedelta(minutes=3),
        duration_s=30.0,
        analysis=None,
        halt=1,
    )
    too_close = JudgedCandidate(
        event_id="evt_2",
        start_time=_START + timedelta(seconds=45),
        duration_s=30.0,
        analysis=None,
    )
    far = _candidate(3, analysis=None)
    ranks = {"evt_0": 1, "evt_1": 2, "evt_2": 3, "evt_3": 4}

    selection = select_judged_candidates(
        (same_halt_first, same_halt_second, too_close, far),
        ranks=ranks,
        requires_analysis=False,
    )

    assert _reason(selection, "evt_0") == REASON_SELECTED
    assert _reason(selection, "evt_1") == REASON_SAME_HALT
    assert _reason(selection, "evt_2") == REASON_TOO_CLOSE
    assert _reason(selection, "evt_3") == REASON_SELECTED


def test_rank_only_selection_cannot_apply_the_car_park_or_standing_still_checks() -> None:
    """Both read `.analysis`; without one, a tournament's pick cannot be screened by them."""
    candidates = (
        _candidate(0, analysis=None),
        _candidate(1, analysis=None),
    )
    ranks = {"evt_0": 1, "evt_1": 2}

    selection = select_judged_candidates(candidates, ranks=ranks, requires_analysis=False)

    assert REASON_PRIVATE_RESIDENCE not in {v.reason for v in selection.verdicts}
    assert REASON_STANDING not in {v.reason for v in selection.verdicts}
    assert set(selection.selected_event_ids) == {"evt_0", "evt_1"}


def test_rank_only_selection_still_takes_fixed_shots_first() -> None:
    fixed = _candidate(0, analysis=None)
    ranked_last = _candidate(1, analysis=None)
    ranks = {"evt_0": 2, "evt_1": 1}

    selection = select_judged_candidates(
        (fixed, ranked_last), ranks=ranks, required={"evt_0"}, requires_analysis=False
    )

    assert _reason(selection, "evt_0") == REASON_FIXED_SHOT
    assert _reason(selection, "evt_1") == REASON_SELECTED


def test_a_required_window_is_kept_even_with_the_rider_in_the_mirror() -> None:
    from dataclasses import replace

    mirror = _candidate(0, analysis=replace(_analysis(), rider_visible="large"))

    selection = select_judged_candidates(
        (mirror, _candidate(1)), required={"evt_0"}, parked_allowed={"evt_0"}
    )

    assert _reason(selection, "evt_0") == REASON_FIXED_SHOT


def test_two_required_windows_cannot_overlap_in_ride_time() -> None:
    """A stop's own picture that begins inside the shot of pulling in gives way."""
    pulling_in = _candidate(0, duration_s=30.0)
    place = _candidate(1, minutes=0.25, duration_s=30.0)  # fifteen seconds later
    later = _candidate(2, duration_s=30.0)

    selection = select_judged_candidates(
        (pulling_in, place, later), required={"evt_0", "evt_1", "evt_2"}
    )

    assert _reason(selection, "evt_0") == REASON_FIXED_SHOT
    assert _reason(selection, "evt_1") == REASON_TOO_CLOSE
    assert _reason(selection, "evt_2") == REASON_FIXED_SHOT
