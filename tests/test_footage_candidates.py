"""Synthetic-fixture tests for drawing candidates from the footage itself."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from app.footage_candidates import (
    FOOTAGE_CANDIDATE_SCHEMA_VERSION,
    FootageCandidate,
    FootageCandidateError,
    candidate_id_for,
    enumerate_footage_candidates,
    summarise_footage_candidates,
    turn_candidates,
    windows_at,
)
from app.gps.turns import SharpTurn
from app.video import VideoCatalog, VideoCatalogEntry

_RIDE_START = datetime(2026, 5, 1, 9, 0, 0, tzinfo=UTC)
_RIDE_END = _RIDE_START + timedelta(hours=4)


def _catalog(
    *,
    recordings: tuple[tuple[float, float], ...] = ((600.0, 1_200.0),),
    offset_s: float = 0.0,
) -> VideoCatalog:
    """Recordings given as (seconds after the ride started, duration)."""
    return VideoCatalog(
        entries=tuple(
            VideoCatalogEntry(
                asset_id=f"asset-{index}",
                file_name=f"GH01{index:04d}.MP4",
                recorded_start_time=_RIDE_START + timedelta(seconds=start_s - offset_s),
                duration_s=duration_s,
            )
            for index, (start_s, duration_s) in enumerate(recordings)
        ),
        video_to_gps_offset_s=offset_s,
    )


def _enumerate(catalog: VideoCatalog, **kwargs):
    return enumerate_footage_candidates(catalog, _RIDE_START, _RIDE_END, **kwargs)


def test_a_recording_yields_many_candidates_not_one() -> None:
    """The point: twenty minutes of footage is not a single candidate."""
    candidates = _enumerate(_catalog(recordings=((600.0, 1_200.0),)))

    # A twenty-minute recording at a thirty-second stride.
    assert len(candidates) == 40
    assert all(candidate.duration_s == 12.0 for candidate in candidates)


def test_candidates_come_back_in_ride_order() -> None:
    candidates = _enumerate(_catalog(recordings=((3_600.0, 300.0), (600.0, 300.0))))

    starts = [candidate.start_time for candidate in candidates]
    assert starts == sorted(starts)


def test_a_window_running_past_its_recording_is_not_footage() -> None:
    candidates = _enumerate(_catalog(recordings=((600.0, 45.0),)), window_s=12.0, stride_s=30.0)

    # Offsets 0 and 30 end at 12 s and 42 s, inside a 45 s recording. The next
    # would start at 60 s, past its end.
    assert [candidate.start_offset_s for candidate in candidates] == [0.0, 30.0]


def test_footage_from_outside_the_ride_is_left_out() -> None:
    """Filming before setting off or after arriving is not this journey."""
    before = _catalog(recordings=((-3_600.0, 600.0),))
    after = _catalog(recordings=((4 * 3_600.0 + 60.0, 600.0),))

    assert _enumerate(before) == ()
    assert _enumerate(after) == ()


def test_the_clock_correction_places_the_footage_on_the_ride() -> None:
    """A camera thirteen hours out still has its windows land on the ride."""
    wrong_clock = _catalog(recordings=((600.0, 600.0),), offset_s=-13 * 3600.0)

    candidates = _enumerate(wrong_clock)

    assert candidates
    assert all(_RIDE_START <= c.start_time <= _RIDE_END for c in candidates)


def test_a_window_is_named_by_itself_so_two_runs_agree() -> None:
    first = _enumerate(_catalog())
    second = _enumerate(_catalog())

    assert [c.candidate_id for c in first] == [c.candidate_id for c in second]
    assert candidate_id_for(_RIDE_START, 12.0) == candidate_id_for(_RIDE_START, 12.0)
    assert candidate_id_for(_RIDE_START, 12.0) != candidate_id_for(_RIDE_START, 13.0)


def test_overlapping_recordings_do_not_double_one_window() -> None:
    """Two recordings can overlap after a clock correction."""
    candidates = _enumerate(_catalog(recordings=((600.0, 300.0), (600.0, 300.0))))

    ids = [candidate.candidate_id for candidate in candidates]
    assert len(ids) == len(set(ids))


def test_a_wider_stride_yields_fewer_candidates() -> None:
    catalog = _catalog(recordings=((600.0, 1_200.0),))

    tight = _enumerate(catalog, stride_s=15.0)
    loose = _enumerate(catalog, stride_s=60.0)

    assert len(tight) > len(loose)


def test_a_recording_too_short_for_one_window_yields_nothing() -> None:
    assert _enumerate(_catalog(recordings=((600.0, 5.0),)), window_s=12.0) == ()


def test_impossible_windows_and_spans_are_refused() -> None:
    catalog = _catalog()

    with pytest.raises(FootageCandidateError, match="window and stride"):
        _enumerate(catalog, window_s=0.0)
    with pytest.raises(FootageCandidateError, match="positive duration"):
        enumerate_footage_candidates(catalog, _RIDE_END, _RIDE_START)
    with pytest.raises(FootageCandidateError, match="timezone-aware"):
        enumerate_footage_candidates(
            catalog, datetime(2026, 5, 1, 9, 0, 0), _RIDE_END.replace(tzinfo=None)
        )


def test_a_candidate_needs_its_identifiers_and_a_real_window() -> None:
    with pytest.raises(ValueError, match="needs its identifiers"):
        FootageCandidate(
            candidate_id="",
            asset_id="a",
            start_offset_s=0.0,
            duration_s=12.0,
            start_time=_RIDE_START,
        )
    with pytest.raises(ValueError, match="positive duration"):
        FootageCandidate(
            candidate_id="c",
            asset_id="a",
            start_offset_s=0.0,
            duration_s=0.0,
            start_time=_RIDE_START,
        )


def test_the_summary_says_how_much_of_the_ride_is_on_offer() -> None:
    candidates = _enumerate(_catalog(recordings=((600.0, 1_200.0),)))

    summary = summarise_footage_candidates(candidates, ride_duration_s=4 * 3600.0)

    assert summary["schema_version"] == FOOTAGE_CANDIDATE_SCHEMA_VERSION
    assert summary["candidate_count"] == 40
    assert summary["candidate_seconds"] == pytest.approx(480.0)
    assert 0.0 < summary["share_of_ride"] < 1.0
    # Counts and durations only.
    assert set(summary) == {
        "schema_version",
        "candidate_count",
        "candidate_seconds",
        "ride_duration_s",
        "share_of_ride",
    }


# --- windows for the turns the stride missed (Q1) -------------------------------------------


def _turn(at_s: float, degrees: float = 100.0, lasting_s: float = 6.0) -> SharpTurn:
    start = _RIDE_START + timedelta(seconds=at_s - lasting_s / 2)
    return SharpTurn(start, start + timedelta(seconds=lasting_s), degrees)


def test_a_turn_between_two_windows_gets_a_window_centred_on_it() -> None:
    catalog = _catalog(recordings=((600.0, 1_200.0),))
    existing = _enumerate(catalog)
    # Stride windows start at 600, 630, 660, ...; 600+20 = 620 s lies in no window.
    turn = _turn(620.0)
    assert not any(c.start_time <= turn.middle <= c.end_time for c in existing)

    added = turn_candidates(catalog, _RIDE_START, _RIDE_END, (turn,), existing)

    assert len(added) == 1
    (window,) = added
    assert window.start_time == turn.middle - timedelta(seconds=6.0)
    assert window.start_offset_s == 14.0 and window.duration_s == 12.0
    assert window.asset_id == "asset-0"


def test_a_turn_already_inside_a_window_adds_nothing() -> None:
    catalog = _catalog(recordings=((600.0, 1_200.0),))
    existing = _enumerate(catalog)

    assert turn_candidates(catalog, _RIDE_START, _RIDE_END, (_turn(606.0),), existing) == ()


def test_a_turn_outside_every_recording_adds_nothing() -> None:
    catalog = _catalog(recordings=((600.0, 1_200.0),))

    assert turn_candidates(catalog, _RIDE_START, _RIDE_END, (_turn(300.0),), ()) == ()


def test_the_sharpest_turns_come_first_when_capped() -> None:
    catalog = _catalog(recordings=((600.0, 1_200.0),))
    existing = _enumerate(catalog)
    gentle, sharp = _turn(620.0, degrees=95.0), _turn(680.0, degrees=-150.0)

    added = turn_candidates(catalog, _RIDE_START, _RIDE_END, (gentle, sharp), existing, max_extra=1)

    assert len(added) == 1 and added[0].start_time == sharp.middle - timedelta(seconds=6.0)


def test_a_turn_at_the_end_of_a_recording_is_kept_inside_it() -> None:
    catalog = _catalog(recordings=((600.0, 100.0),))  # the recording ends at 700 s
    turn = _turn(698.0)

    (window,) = turn_candidates(catalog, _RIDE_START, _RIDE_END, (turn,), ())

    assert window.end_time == _RIDE_START + timedelta(seconds=700.0)
    assert window.start_offset_s == 88.0


def test_the_clock_offset_places_the_turn_in_the_recording() -> None:
    catalog = _catalog(recordings=((600.0, 1_200.0),), offset_s=30.0)
    existing = _enumerate(catalog)

    (window,) = turn_candidates(catalog, _RIDE_START, _RIDE_END, (_turn(620.0),), existing)

    assert window.start_time == _RIDE_START + timedelta(seconds=614.0)
    assert window.start_offset_s == 14.0, "offsets are on the recording's own clock"


# --- windows at the moments the track proves -----------------------------------


def test_a_window_is_made_at_each_asked_start_inside_a_recording() -> None:
    catalog = _catalog(recordings=((600.0, 1_200.0),))
    wanted = (_RIDE_START + timedelta(seconds=700.0), _RIDE_START + timedelta(seconds=5_000.0))

    made = windows_at(catalog, _RIDE_START, _RIDE_END, wanted, ())

    assert [w.start_time for w in made] == [wanted[0]]
    assert made[0].start_offset_s == 100.0


def test_a_window_already_starting_there_is_not_bought_twice() -> None:
    catalog = _catalog(recordings=((600.0, 1_200.0),))
    existing = _enumerate(catalog, stride_s=60.0)
    near = existing[3].start_time + timedelta(seconds=2.0)

    assert windows_at(catalog, _RIDE_START, _RIDE_END, (near,), existing) == ()
    far = existing[3].start_time + timedelta(seconds=5.0)
    assert len(windows_at(catalog, _RIDE_START, _RIDE_END, (far,), existing)) == 1


def test_a_window_asked_at_the_end_of_a_recording_slides_back_inside_it() -> None:
    catalog = _catalog(recordings=((600.0, 1_200.0),))
    at_the_end = _RIDE_START + timedelta(seconds=600.0 + 1_195.0)

    made = windows_at(catalog, _RIDE_START, _RIDE_END, (at_the_end,), ())

    assert len(made) == 1
    assert made[0].start_offset_s + made[0].duration_s == 1_200.0


def test_windows_at_refuses_nonsense() -> None:
    catalog = _catalog()
    with pytest.raises(FootageCandidateError):
        windows_at(catalog, _RIDE_START, _RIDE_END, (), (), window_s=0.0)
    with pytest.raises(FootageCandidateError):
        windows_at(catalog, _RIDE_START, _RIDE_END, (), (), tolerance_s=-1.0)
