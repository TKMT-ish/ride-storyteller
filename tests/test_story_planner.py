from datetime import UTC, datetime, timedelta

import pytest

from app.agents import RuleBasedStoryPlanner, StoryOutputLanguage
from app.contracts import GpsEvent, Location, RouteSummary, VideoQuery


def _event(event_id: str, event_type: str, importance: float, minute: int) -> GpsEvent:
    timestamp = datetime(2026, 8, 10, tzinfo=UTC) + timedelta(minutes=minute)
    return GpsEvent(
        event_id=event_id,
        event_type=event_type,
        start_time=timestamp,
        end_time=timestamp,
        location=Location(-45.0, 168.0),
        importance_hint=importance,
        evidence=(event_type,),
        video_query=VideoQuery("unknown.mp4", 0, 30),
    )


def _summary() -> RouteSummary:
    start = datetime(2026, 8, 10, tzinfo=UTC)
    return RouteSummary(3, start, start + timedelta(hours=2), 123_400, 7_200, 500, 300)


def test_story_plan_uses_route_and_event_data_without_visual_claims() -> None:
    plan = RuleBasedStoryPlanner().plan(
        _summary(),
        (
            _event("departure", "departure", 0.55, 0),
            _event("elevation", "elevation_change", 0.70, 30),
            _event("arrival", "arrival_candidate", 0.75, 120),
        ),
        target_duration_s=480,
    )
    assert plan.title == "123.4kmをたどる旅"
    assert plan.selected_event_ids == ("departure", "elevation", "arrival")
    assert [chapter.title for chapter in plan.chapters] == ["出発", "景色の変化", "到着と余韻"]
    assert sum(chapter.target_duration_s for chapter in plan.chapters) == pytest.approx(480)
    assert plan.planning_provider == "rule_based_mock"


def test_story_plan_rejects_duration_outside_mvp_range() -> None:
    with pytest.raises(ValueError, match="target_duration_s"):
        RuleBasedStoryPlanner().plan(
            _summary(),
            (_event("departure", "departure", 0.55, 0),),
            target_duration_s=60,
        )


def test_story_plan_breaks_equal_priority_ties_by_stable_event_id() -> None:
    first_input = _event("stop_z", "stop", 0.50, 20)
    second_input = _event("stop_a", "stop", 0.50, 20)

    plan = RuleBasedStoryPlanner().plan(
        _summary(),
        (first_input, second_input),
        target_duration_s=300,
    )

    assert plan.selected_event_ids == ("stop_a",)


def test_story_plan_generates_english_user_facing_text() -> None:
    plan = RuleBasedStoryPlanner().plan(
        _summary(),
        (
            _event("departure", "departure", 0.55, 0),
            _event("elevation", "elevation_change", 0.70, 30),
            _event("arrival", "arrival_candidate", 0.75, 120),
        ),
        target_duration_s=480,
        output_language=StoryOutputLanguage.ENGLISH,
    )

    assert plan.title == "A 123.4 km journey"
    assert [chapter.title for chapter in plan.chapters] == [
        "Departure",
        "Changing scenery",
        "Arrival and reflection",
    ]
    assert plan.chapters[1].selection_rationale == (
        "An elevation change makes this moment worth checking on video."
    )


def test_story_plan_language_does_not_change_structural_identifiers() -> None:
    events = (
        _event("departure", "departure", 0.55, 0),
        _event("elevation", "elevation_change", 0.70, 30),
        _event("arrival", "arrival_candidate", 0.75, 120),
    )
    japanese = RuleBasedStoryPlanner().plan(_summary(), events, target_duration_s=480)
    english = RuleBasedStoryPlanner().plan(
        _summary(),
        events,
        target_duration_s=480,
        output_language=StoryOutputLanguage.ENGLISH,
    )

    assert english.selected_event_ids == japanese.selected_event_ids
    assert [chapter.chapter_id for chapter in english.chapters] == [
        chapter.chapter_id for chapter in japanese.chapters
    ]
    assert [chapter.event_id for chapter in english.chapters] == [
        chapter.event_id for chapter in japanese.chapters
    ]
    assert [chapter.narrative_role for chapter in english.chapters] == [
        chapter.narrative_role for chapter in japanese.chapters
    ]


def test_story_plan_selected_events_preserves_repeated_types_and_chronology() -> None:
    events = (
        _event("speed_late", "speed_change", 0.9, 90),
        _event("direction", "direction_change", 0.7, 40),
        _event("speed_early", "speed_change", 0.5, 20),
    )

    plan = RuleBasedStoryPlanner().plan_selected_events(
        _summary(),
        events,
        target_duration_s=300,
    )

    assert plan.selected_event_ids == ("speed_early", "direction", "speed_late")
    assert [chapter.narrative_role for chapter in plan.chapters] == [
        "speed_change",
        "direction_change",
        "speed_change",
    ]
    assert plan.planning_provider == "rule_based_video_coverage"
