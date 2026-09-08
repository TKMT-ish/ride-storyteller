"""Synthetic-fixture tests for the owner's view of their film's story.

Held: the beats come out in screen order under their chapters, the model's
words ride beside each window (this is the private detail view, not the
console), a cold open is reported as such, the film's availability is
reported without a path, and a package without a plan says so.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path

import pytest

from app.agents import StoryOutputLanguage
from app.analysis_ranking import WINDOW_RANKING_FILE_NAME, WindowRanking, write_window_ranking
from app.analysis_record import (
    VIDEO_ANALYSIS_RECORD_FILE_NAME,
    AnalysedEvent,
    VideoAnalysisRecord,
    write_video_analysis_record,
)
from app.contracts import VideoAnalysis
from app.gap_chapters import GapChapterCard, GapCharacter
from app.journey_gaps import JourneyGapKind
from app.story_package import (
    JOURNEY_STORY_PLAN_FILE_NAME,
    JourneyStoryPlan,
    StoryPlanBeat,
    write_journey_story_plan,
)
from app.story_timeline import StoryBeatKind
from app.web.private_journey_story import (
    PRIVATE_JOURNEY_STORY_SCHEMA_VERSION,
    SCORED_FILM_FILE_NAME,
    PrivateJourneyStoryError,
    StoryView,
)

_T0 = datetime(2026, 5, 1, 9, 0, 0, tzinfo=UTC)


def _analysis(description: str, road: str, interest: float, story: float) -> VideoAnalysis:
    return VideoAnalysis(
        asset_id="asset-1",
        start_offset_s=0.0,
        end_offset_s=12.0,
        visual_description=description,
        road_type=road,
        scenery_tags=("sky",),
        weather_visible="clear",
        visual_interest_score=interest,
        story_relevance_score=story,
        confidence=0.9,
        analysis_provider="gemini",
    )


def _card(title: str, body: str, character: GapCharacter, kind: JourneyGapKind) -> GapChapterCard:
    return GapChapterCard(
        kind=kind, character=character, title=title, body=body, screen_duration_s=6.0
    )


def _package(root: Path, *, with_plan: bool = True, with_film: bool = True) -> Path:
    root.mkdir(parents=True, exist_ok=True)
    write_video_analysis_record(
        root / VIDEO_ANALYSIS_RECORD_FILE_NAME,
        VideoAnalysisRecord(
            (
                AnalysedEvent(
                    "w-open", _analysis("A gorge from the saddle", "mountain road", 0.9, 0.9)
                ),
                AnalysedEvent("w-1", _analysis("A straight highway", "highway", 0.6, 0.6)),
                AnalysedEvent(
                    "w-2", _analysis("A roundabout in town", "suburban street", 0.7, 0.8)
                ),
            )
        ),
        overwrite=True,
    )
    write_window_ranking(
        root / WINDOW_RANKING_FILE_NAME,
        WindowRanking(provider="gemini", ranks={"w-open": 1, "w-2": 2, "w-1": 3}),
        overwrite=True,
    )
    if with_plan:
        beats = (
            StoryPlanBeat(StoryBeatKind.FOOTAGE, 10.0, event_id="w-open"),
            StoryPlanBeat(
                StoryBeatKind.GAP_CARD,
                6.0,
                card=_card(
                    "出発",
                    "出発 · 12.0km",
                    GapCharacter.DEPARTURE,
                    JourneyGapKind.BEFORE_FIRST_CLIP,
                ),
            ),
            StoryPlanBeat(StoryBeatKind.FOOTAGE, 8.0, event_id="w-1"),
            StoryPlanBeat(
                StoryBeatKind.GAP_CARD,
                6.0,
                card=_card(
                    "町を抜ける",
                    "出発から1時間 · 40.0km",
                    GapCharacter.TOWN,
                    JourneyGapKind.BETWEEN_CLIPS,
                ),
            ),
            StoryPlanBeat(StoryBeatKind.FOOTAGE, 6.0, event_id="w-2"),
            StoryPlanBeat(
                StoryBeatKind.GAP_CARD,
                6.0,
                card=_card(
                    "今日はここまで",
                    "52.0km · 1時間30分",
                    GapCharacter.ARRIVAL,
                    JourneyGapKind.AFTER_LAST_CLIP,
                ),
            ),
        )
        write_journey_story_plan(
            root / JOURNEY_STORY_PLAN_FILE_NAME,
            JourneyStoryPlan(
                beats=beats,
                output_language=StoryOutputLanguage.JAPANESE,
                footage_screen_duration_s=24.0,
                total_screen_duration_s=42.0,
            ),
        )
    if with_film:
        (root / SCORED_FILM_FILE_NAME).write_bytes(b"\x00" * 2_000_000)
    return root


def test_the_story_comes_out_in_screen_order_under_its_chapters(tmp_path: Path) -> None:
    payload = StoryView(_package(tmp_path / "p")).payload()

    assert payload["schema_version"] == PRIVATE_JOURNEY_STORY_SCHEMA_VERSION
    assert payload["chapter_count"] == 3
    assert payload["window_count"] == 3
    titles = [c["title"] for c in payload["chapters"]]
    assert titles == ["出発", "町を抜ける", "今日はここまで"]
    assert [len(c["windows"]) for c in payload["chapters"]] == [1, 1, 0]
    assert payload["chapters"][0]["windows"][0]["at_s"] == 16.0
    assert payload["total_screen_duration_s"] == 42.0


def test_the_cold_open_is_the_window_before_any_chapter(tmp_path: Path) -> None:
    payload = StoryView(_package(tmp_path / "p")).payload()

    cold = payload["cold_open"]
    assert cold is not None
    assert cold["at_s"] == 0.0
    assert cold["rank"] == 1
    assert "gorge" in cold["description"]


def test_each_window_carries_the_models_words_and_its_standing(tmp_path: Path) -> None:
    """This is the owner's private view; the model's words belong here."""
    payload = StoryView(_package(tmp_path / "p")).payload()

    window = payload["chapters"][1]["windows"][0]
    assert window["judged"] is True
    assert window["rank"] == 2
    assert window["interest"] == 0.7 and window["story"] == 0.8
    assert window["road"] == "suburban street"
    assert "roundabout" in window["description"]


def test_the_film_is_reported_without_a_path(tmp_path: Path) -> None:
    package = _package(tmp_path / "p")
    payload = StoryView(package).payload()

    assert payload["film"] == {
        "available": True,
        "variant": "scored",
        "megabytes": 2.0,
        "file_name": SCORED_FILM_FILE_NAME,
    }
    assert payload["package"] == package.name, "the folder's name, so the page can say where"
    assert str(package) not in json.dumps(payload), "never the absolute path"
    assert "asset-1" not in json.dumps(payload)
    assert StoryView(package).film_path() == package / SCORED_FILM_FILE_NAME


def test_no_film_yet_is_said_plainly(tmp_path: Path) -> None:
    view = StoryView(_package(tmp_path / "p", with_film=False))

    assert view.payload()["film"]["available"] is False
    assert view.film_path() is None


def test_a_package_without_a_plan_says_so(tmp_path: Path) -> None:
    with pytest.raises(PrivateJourneyStoryError, match="no story plan"):
        StoryView(_package(tmp_path / "p", with_plan=False)).payload()


def test_a_window_the_judgement_lacks_is_marked_unjudged(tmp_path: Path) -> None:
    package = _package(tmp_path / "p")
    (package / VIDEO_ANALYSIS_RECORD_FILE_NAME).unlink()

    payload = StoryView(package).payload()

    assert payload["cold_open"] == {
        "judged": False,
        "rank": None,
        "at_s": 0.0,
        "screen_duration_s": 10.0,
    }


def test_a_title_over_footage_opens_its_chapter_in_the_view(tmp_path: Path) -> None:
    from app.story_package import load_journey_story_plan, write_journey_story_plan
    from app.story_titles import title_over_footage

    root = _package(tmp_path / "package")
    plan_path = root / "journey-story-plan.json"
    write_journey_story_plan(plan_path, title_over_footage(load_journey_story_plan(plan_path)))

    payload = StoryView(root).payload()

    titled = [c for c in payload["chapters"] if c["over_footage"]]
    assert titled, "a chapter card followed by a window now rides over it"
    assert all(c["windows"] for c in titled), "the window it rides on is listed under it"
    assert [c["title"] for c in payload["chapters"]] == ["出発", "町を抜ける", "今日はここまで"]
