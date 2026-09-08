"""Synthetic-fixture tests for the written journey story plan."""

from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from app.agents.story_planner import StoryOutputLanguage
from app.gap_chapters import GapChapterCard, GapCharacter
from app.journey_gaps import JourneyGapKind, JourneyGapPlan, JourneyGapSegment
from app.story_package import (
    JOURNEY_STORY_PLAN_SCHEMA_VERSION,
    JourneyStoryPlan,
    JourneyStoryPlanError,
    StoryPlanBeat,
    build_journey_story_plan,
    load_journey_story_plan,
    write_journey_story_plan,
)
from app.story_timeline import StoryBeatKind, TimelineFootage, build_story_timeline

_START = datetime(2026, 5, 1, 9, 0, 0, tzinfo=UTC)


def _at(offset_s: float) -> datetime:
    return _START + timedelta(seconds=offset_s)


def _timeline():
    """gap, footage, gap, footage, gap -- one whole ride."""
    footage = tuple(
        TimelineFootage(
            event_id=f"evt_{index}",
            start_time=_at(3600.0 * (index + 1)),
            end_time=_at(3600.0 * (index + 1) + 30.0),
        )
        for index in range(2)
    )
    gaps = (
        JourneyGapSegment(
            kind=JourneyGapKind.BEFORE_FIRST_CLIP,
            start_time=_at(0.0),
            end_time=_at(3600.0),
            distance_m=42_000.0,
            elevation_gain_m=300.0,
            elevation_loss_m=120.0,
        ),
        JourneyGapSegment(
            kind=JourneyGapKind.BETWEEN_CLIPS,
            start_time=_at(3630.0),
            end_time=_at(7200.0),
            distance_m=38_000.0,
            elevation_gain_m=90.0,
            elevation_loss_m=310.0,
        ),
        JourneyGapSegment(
            kind=JourneyGapKind.AFTER_LAST_CLIP,
            start_time=_at(7230.0),
            end_time=_at(9000.0),
            distance_m=12_000.0,
            elevation_gain_m=20.0,
            elevation_loss_m=180.0,
        ),
    )
    return build_story_timeline(footage, JourneyGapPlan(gaps))


def _plan():
    return build_journey_story_plan(_timeline())


def test_plan_keeps_the_ride_order_and_pairs_each_gap_with_its_card() -> None:
    plan = _plan()

    assert [beat.kind for beat in plan.beats] == [
        StoryBeatKind.GAP_CARD,
        StoryBeatKind.FOOTAGE,
        StoryBeatKind.GAP_CARD,
        StoryBeatKind.FOOTAGE,
        StoryBeatKind.GAP_CARD,
    ]
    assert [beat.card.kind for beat in plan.card_beats] == [
        JourneyGapKind.BEFORE_FIRST_CLIP,
        JourneyGapKind.BETWEEN_CLIPS,
        JourneyGapKind.AFTER_LAST_CLIP,
    ]


def test_a_footage_beat_names_its_event_and_carries_no_card() -> None:
    plan = _plan()

    for beat in plan.footage_beats:
        assert beat.event_id is not None
        assert beat.card is None
    for beat in plan.card_beats:
        assert beat.event_id is None
        assert beat.card is not None


def test_written_plan_round_trips(tmp_path: Path) -> None:
    plan = _plan()
    path = tmp_path / "journey-story-plan.json"

    write_journey_story_plan(path, plan)

    assert load_journey_story_plan(path) == plan


def test_written_plan_is_readable_json_with_its_schema(tmp_path: Path) -> None:
    timeline = _timeline()
    path = tmp_path / "journey-story-plan.json"
    write_journey_story_plan(
        path,
        build_journey_story_plan(timeline),
    )

    payload = json.loads(path.read_text(encoding="utf-8"))

    assert payload["schema_version"] == JOURNEY_STORY_PLAN_SCHEMA_VERSION
    assert payload["beats"][0]["card"]["title"]
    assert payload["beats"][1]["event_id"] == "evt_0"


def test_language_choice_survives_the_round_trip(tmp_path: Path) -> None:
    plan = build_journey_story_plan(
        _timeline(),
        output_language=StoryOutputLanguage.ENGLISH,
    )
    path = tmp_path / "journey-story-plan.json"
    write_journey_story_plan(path, plan)

    loaded = load_journey_story_plan(path)

    assert loaded.output_language is StoryOutputLanguage.ENGLISH
    assert loaded.card_beats[0].card.title == "The ride begins"


def test_an_unknown_schema_is_refused(tmp_path: Path) -> None:
    path = tmp_path / "journey-story-plan.json"
    write_journey_story_plan(path, _plan())
    payload = json.loads(path.read_text(encoding="utf-8"))
    payload["schema_version"] = "journey-story-plan-v0"
    path.write_text(json.dumps(payload), encoding="utf-8")

    with pytest.raises(JourneyStoryPlanError, match="unsupported"):
        load_journey_story_plan(path)


def test_malformed_and_unreadable_plans_are_refused(tmp_path: Path) -> None:
    broken = tmp_path / "broken.json"
    broken.write_text("{not json", encoding="utf-8")
    with pytest.raises(JourneyStoryPlanError, match="unreadable"):
        load_journey_story_plan(broken)

    not_an_object = tmp_path / "list.json"
    not_an_object.write_text("[]", encoding="utf-8")
    with pytest.raises(JourneyStoryPlanError, match="malformed"):
        load_journey_story_plan(not_an_object)

    missing_field = tmp_path / "partial.json"
    missing_field.write_text(
        json.dumps({"schema_version": JOURNEY_STORY_PLAN_SCHEMA_VERSION, "beats": []}),
        encoding="utf-8",
    )
    with pytest.raises(JourneyStoryPlanError, match="malformed"):
        load_journey_story_plan(missing_field)


def test_a_missing_plan_is_refused(tmp_path: Path) -> None:
    with pytest.raises(JourneyStoryPlanError, match="unavailable"):
        load_journey_story_plan(tmp_path / "absent.json")


def test_a_symlinked_plan_is_refused_for_reading_and_writing(tmp_path: Path) -> None:
    real = tmp_path / "journey-story-plan.json"
    write_journey_story_plan(real, _plan())
    link = tmp_path / "linked.json"
    link.symlink_to(real)

    with pytest.raises(JourneyStoryPlanError, match="unavailable"):
        load_journey_story_plan(link)
    with pytest.raises(JourneyStoryPlanError, match="unsafe"):
        write_journey_story_plan(link, _plan())


def test_writing_over_a_plan_needs_overwrite(tmp_path: Path) -> None:
    path = tmp_path / "journey-story-plan.json"
    write_journey_story_plan(path, _plan())

    with pytest.raises(FileExistsError):
        write_journey_story_plan(path, _plan(), overwrite=False)

    # The default is to replace, so a rerun never leaves a stale film shape.
    write_journey_story_plan(path, _plan())
    assert load_journey_story_plan(path) == _plan()


def test_a_failed_write_leaves_no_temporary_file(tmp_path: Path) -> None:
    path = tmp_path / "journey-story-plan.json"

    class Unserializable:
        pass

    plan = _plan()
    object.__setattr__(plan, "output_language", Unserializable())
    with pytest.raises(Exception):
        write_journey_story_plan(path, plan)

    assert list(tmp_path.iterdir()) == []


def test_a_plan_is_as_long_as_its_material() -> None:
    """Nothing pads the film to a number; its length follows the beats."""
    timeline = _timeline()

    plan = build_journey_story_plan(timeline)

    assert plan.total_screen_duration_s == pytest.approx(
        sum(beat.screen_duration_s for beat in plan.beats)
    )
    assert plan.total_screen_duration_s == pytest.approx(timeline.total_screen_duration_s)


def test_a_cards_place_on_the_clock_survives_the_round_trip(tmp_path: Path) -> None:
    plan = _plan()
    beats = list(plan.beats)
    for index, beat in enumerate(beats):
        if beat.card is not None:
            beats[index] = StoryPlanBeat(
                kind=beat.kind,
                screen_duration_s=beat.screen_duration_s,
                card=GapChapterCard(
                    kind=beat.card.kind,
                    character=beat.card.character,
                    title=beat.card.title,
                    body=beat.card.body,
                    screen_duration_s=beat.card.screen_duration_s,
                    since_departure_s=1800.0,
                    duration_s=900.0,
                ),
            )
            break
    timed = JourneyStoryPlan(
        beats=tuple(beats),
        output_language=plan.output_language,
        footage_screen_duration_s=plan.footage_screen_duration_s,
        total_screen_duration_s=plan.total_screen_duration_s,
    )
    path = tmp_path / "plan.json"
    write_journey_story_plan(path, timed)

    loaded = load_journey_story_plan(path)
    assert loaded == timed
    assert any(b.card is not None and b.card.is_on_the_clock for b in loaded.beats)


def test_footage_may_carry_the_chapters_title_and_it_round_trips(tmp_path: Path) -> None:
    title = GapChapterCard(
        kind=JourneyGapKind.BETWEEN_CLIPS,
        character=GapCharacter.CLIMB,
        title="登る",
        body="本文",
        screen_duration_s=5.0,
    )
    titled = JourneyStoryPlan(
        beats=(StoryPlanBeat(StoryBeatKind.FOOTAGE, 8.0, event_id="w-1", card=title),),
        output_language=StoryOutputLanguage.JAPANESE,
        footage_screen_duration_s=8.0,
        total_screen_duration_s=8.0,
    )
    path = tmp_path / "plan.json"
    write_journey_story_plan(path, titled)

    loaded = load_journey_story_plan(path)
    assert loaded == titled
    assert loaded.beats[0].is_titled_footage
    assert loaded.beats_with_cards == loaded.beats and loaded.card_beats == ()


def test_a_title_cannot_outlast_the_window_under_it() -> None:
    title = GapChapterCard(
        kind=JourneyGapKind.BETWEEN_CLIPS,
        character=GapCharacter.CLIMB,
        title="登る",
        body="本文",
        screen_duration_s=9.0,
    )
    with pytest.raises(ValueError, match="outlast"):
        StoryPlanBeat(StoryBeatKind.FOOTAGE, 8.0, event_id="w-1", card=title)


def test_where_a_cut_begins_inside_its_window_round_trips(tmp_path: Path) -> None:
    plan = JourneyStoryPlan(
        beats=(StoryPlanBeat(StoryBeatKind.FOOTAGE, 6.0, event_id="w-1", source_offset_s=6.0),),
        output_language=StoryOutputLanguage.JAPANESE,
        footage_screen_duration_s=6.0,
        total_screen_duration_s=6.0,
    )
    path = tmp_path / "plan.json"
    write_journey_story_plan(path, plan)

    assert load_journey_story_plan(path) == plan
    assert "source_offset_s" not in json.dumps(
        StoryPlanBeat(StoryBeatKind.FOOTAGE, 6.0, event_id="w-2").to_dict()
    ), "a cut from the window's start writes nothing extra"
    with pytest.raises(ValueError, match="before its window"):
        StoryPlanBeat(StoryBeatKind.FOOTAGE, 6.0, event_id="w-3", source_offset_s=-1.0)
