"""Synthetic-fixture tests for the private journey status view."""

from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from app.agents import StoryOutputLanguage
from app.edit import CandidateEvidenceStatus
from app.journey_gaps import JourneyGapKind, JourneyGapPlan, JourneyGapSegment
from app.local_pipeline import LocalPipelineInputs
from app.story_package import (
    JOURNEY_STORY_PLAN_FILE_NAME,
    build_journey_story_plan,
    write_journey_story_plan,
)
from app.story_timeline import TimelineFootage, build_story_timeline
from app.video import (
    LocalEvidenceDecision,
    LocalEvidenceReview,
    ResolvedCandidateClip,
    VideoCatalog,
    VideoCatalogEntry,
    VideoMatchStatus,
    export_candidate_json,
    write_local_evidence_review,
)
from app.web.private_journey_status import (
    ACTION_FIX_INPUTS,
    ACTION_MAKE_FILM,
    ACTION_NOTHING_LEFT,
    ACTION_SCORE_FILM,
    PRIVATE_JOURNEY_PACKAGE_DIRECTORY_ENV,
    PRIVATE_JOURNEY_STATUS_SCHEMA_VERSION,
    STAGE_FILM,
    STAGE_INPUTS,
    STAGE_MUSIC,
    STAGE_PLAN,
    STATE_BLOCKED,
    STATE_DONE,
    STATE_PENDING,
    PrivateJourneyStatus,
    PrivateJourneyStatusError,
)

_ASSET_ID = "asset-synthetic-1"
_ASSET_START = datetime(2026, 5, 1, 9, 0, 0, tzinfo=UTC)
_TARGET_S = 60.0


def _at(offset_s: float) -> datetime:
    return _ASSET_START + timedelta(seconds=offset_s)


def _package(
    root: Path, *, status: CandidateEvidenceStatus = CandidateEvidenceStatus.CONFIRMED
) -> Path:
    root.mkdir(parents=True, exist_ok=True)
    # The inputs manifest is validated against the file it names.
    (root / "ride.gpx").write_text(
        '<?xml version="1.0" encoding="UTF-8"?>'
        '<gpx version="1.1" creator="test" '
        'xmlns="http://www.topografix.com/GPX/1/1"><trk><trkseg></trkseg></trk></gpx>',
        encoding="utf-8",
    )
    clip = ResolvedCandidateClip(
        chapter_id="chapter_a",
        event_id="evt_private_alpha",
        status=VideoMatchStatus.MATCHED,
        asset_id=_ASSET_ID,
        file_name="a-private-source.mp4",
        start_offset_s=1_800.0,
        end_offset_s=1_860.0,
        reason="synthetic match",
    )
    inputs = LocalPipelineInputs(
        gpx_path=(root / "ride.gpx").resolve(),
        video_root=root.resolve(),
        video_to_gps_offset_s=0.0,
        target_duration_s=_TARGET_S,
        output_language=StoryOutputLanguage.JAPANESE,
    )
    (root / "local-pipeline-inputs.json").write_text(
        json.dumps(inputs.to_dict(), ensure_ascii=False), encoding="utf-8"
    )
    catalog = VideoCatalog(
        entries=(
            VideoCatalogEntry(
                asset_id=_ASSET_ID,
                file_name="a-private-source.mp4",
                recorded_start_time=_ASSET_START,
                duration_s=7_200.0,
            ),
        ),
        video_to_gps_offset_s=0.0,
    )
    (root / "local-video-catalog.json").write_text(
        json.dumps(catalog.to_dict(), ensure_ascii=False), encoding="utf-8"
    )
    (root / "ride-storyteller-candidates.json").write_text(
        export_candidate_json((clip,)), encoding="utf-8"
    )
    write_local_evidence_review(
        root / "evidence-review.json",
        LocalEvidenceReview(
            (
                LocalEvidenceDecision(
                    event_id=clip.event_id,
                    evidence_status=status,
                    evidence_source=(
                        None
                        if status is CandidateEvidenceStatus.AWAITING_VIDEO_EVIDENCE
                        else "synthetic_decision"
                    ),
                ),
            )
        ),
        overwrite=True,
    )
    return root


def _write_plan(root: Path) -> None:
    footage = (
        TimelineFootage(
            event_id="evt_private_alpha", start_time=_at(1_800.0), end_time=_at(1_860.0)
        ),
    )
    gaps = (
        JourneyGapSegment(
            kind=JourneyGapKind.BEFORE_FIRST_CLIP,
            start_time=_at(0.0),
            end_time=_at(1_800.0),
            distance_m=20_000.0,
            elevation_gain_m=300.0,
            elevation_loss_m=40.0,
        ),
        JourneyGapSegment(
            kind=JourneyGapKind.AFTER_LAST_CLIP,
            start_time=_at(1_860.0),
            end_time=_at(3_600.0),
            distance_m=15_000.0,
            elevation_gain_m=20.0,
            elevation_loss_m=280.0,
        ),
    )
    plan = build_journey_story_plan(build_story_timeline(footage, JourneyGapPlan(gaps)))
    write_journey_story_plan(root / JOURNEY_STORY_PLAN_FILE_NAME, plan)


def _stage(payload: dict[str, object], key: str) -> dict[str, object]:
    return next(stage for stage in payload["stages"] if stage["key"] == key)


def test_a_fresh_package_has_checked_inputs_and_nothing_else(tmp_path: Path) -> None:
    package = _package(tmp_path / "package")

    payload = PrivateJourneyStatus.from_directory(package).payload()

    assert payload["schema_version"] == PRIVATE_JOURNEY_STATUS_SCHEMA_VERSION
    assert _stage(payload, STAGE_PLAN)["state"] == STATE_PENDING
    assert _stage(payload, STAGE_FILM)["state"] == STATE_BLOCKED
    assert _stage(payload, STAGE_MUSIC)["state"] == STATE_PENDING


def test_unsettled_evidence_blocks_the_first_stage(tmp_path: Path) -> None:
    package = _package(tmp_path / "package", status=CandidateEvidenceStatus.AWAITING_VIDEO_EVIDENCE)

    payload = PrivateJourneyStatus.from_directory(package).payload()

    inputs = _stage(payload, STAGE_INPUTS)
    assert inputs["state"] == STATE_BLOCKED
    assert "evidence_awaiting_present" in inputs["blocking_reasons"]
    assert payload["next_action"] == ACTION_FIX_INPUTS


def test_a_planned_package_says_what_the_film_will_be(tmp_path: Path) -> None:
    package = _package(tmp_path / "package")
    _write_plan(package)

    payload = PrivateJourneyStatus.from_directory(package).payload()

    plan = _stage(payload, STAGE_PLAN)
    assert plan["state"] == STATE_DONE
    assert plan["beat_count"] == 3
    assert plan["footage_beat_count"] == 1
    assert plan["card_beat_count"] == 2
    assert plan["output_language"] == "ja"
    assert payload["next_action"] == ACTION_MAKE_FILM


def test_the_chapters_are_the_words_the_film_shows(tmp_path: Path) -> None:
    package = _package(tmp_path / "package")
    _write_plan(package)

    chapters = PrivateJourneyStatus.from_directory(package).payload()["chapters"]

    assert [chapter["character"] for chapter in chapters] == ["departure", "arrival"]
    assert chapters[0]["title"] == "旅の始まり"
    assert all(chapter["body"] for chapter in chapters)


def test_a_cut_film_is_finished_and_music_stays_a_choice(tmp_path: Path) -> None:
    package = _package(tmp_path / "package")
    _write_plan(package)
    (package / "ride-storyteller-story-film.mp4").write_bytes(b"x" * 2_000_000)
    (package / "ride-storyteller-story-film.srt").write_text("1\n", encoding="utf-8")

    payload = PrivateJourneyStatus.from_directory(package).payload()

    film = _stage(payload, STAGE_FILM)
    assert film["state"] == STATE_DONE
    assert film["megabytes"] == pytest.approx(2.0)
    assert film["subtitle_count"] == 1
    music = _stage(payload, STAGE_MUSIC)
    assert music["state"] == STATE_DONE and music["scored"] is False
    assert payload["next_action"] != ACTION_SCORE_FILM


def test_a_scored_film_leaves_nothing_to_do(tmp_path: Path) -> None:
    package = _package(tmp_path / "package")
    _write_plan(package)
    (package / "ride-storyteller-story-film.mp4").write_bytes(b"x")
    (package / "ride-storyteller-story-film-scored.mp4").write_bytes(b"x")

    payload = PrivateJourneyStatus.from_directory(package).payload()

    assert _stage(payload, STAGE_MUSIC)["state"] == STATE_DONE
    assert payload["next_action"] == ACTION_NOTHING_LEFT


def test_the_page_never_receives_a_private_identifier(tmp_path: Path) -> None:
    package = _package(tmp_path / "package")
    _write_plan(package)
    (package / "ride-storyteller-story-film.mp4").write_bytes(b"x")

    serialized = json.dumps(
        PrivateJourneyStatus.from_directory(package).payload(), ensure_ascii=False
    )

    for forbidden in (
        "evt_private_alpha",
        _ASSET_ID,
        "a-private-source.mp4",
        str(package),
        "2026-05-01",
        "latitude",
        "chapter_a",
    ):
        assert forbidden not in serialized


def test_the_next_step_is_named_not_spelled_out(tmp_path: Path) -> None:
    """A command line would have to carry the path, which must not be sent."""
    package = _package(tmp_path / "package")
    _write_plan(package)

    payload = PrivateJourneyStatus.from_directory(package).payload()

    assert payload["next_action"] in {
        ACTION_FIX_INPUTS,
        ACTION_MAKE_FILM,
        ACTION_SCORE_FILM,
        ACTION_NOTHING_LEFT,
    }
    assert "python" not in json.dumps(payload, ensure_ascii=False)


def test_a_symlinked_or_missing_package_is_refused(tmp_path: Path) -> None:
    with pytest.raises(PrivateJourneyStatusError, match="unavailable"):
        PrivateJourneyStatus.from_directory(tmp_path / "absent")

    real = _package(tmp_path / "package")
    link = tmp_path / "link"
    link.symlink_to(real, target_is_directory=True)
    with pytest.raises(PrivateJourneyStatusError, match="unavailable"):
        PrivateJourneyStatus.from_directory(link)


def test_an_unreadable_package_is_refused(tmp_path: Path) -> None:
    empty = tmp_path / "empty"
    empty.mkdir()

    with pytest.raises(PrivateJourneyStatusError, match="cannot be read"):
        PrivateJourneyStatus.from_directory(empty).payload()


def test_a_corrupt_plan_stops_the_view(tmp_path: Path) -> None:
    """A plan that cannot be trusted must not be shown as though it were fine."""
    package = _package(tmp_path / "package")
    (package / JOURNEY_STORY_PLAN_FILE_NAME).write_text("{not json", encoding="utf-8")

    with pytest.raises(PrivateJourneyStatusError, match="cannot be trusted"):
        PrivateJourneyStatus.from_directory(package).payload()


def test_the_package_is_read_from_the_environment(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    package = _package(tmp_path / "package")
    monkeypatch.setenv(PRIVATE_JOURNEY_PACKAGE_DIRECTORY_ENV, str(package))

    assert PrivateJourneyStatus.from_environment().package_directory == package.resolve()


def test_an_unconfigured_package_is_refused(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv(PRIVATE_JOURNEY_PACKAGE_DIRECTORY_ENV, raising=False)
    monkeypatch.setattr("app.web.private_journey_status.load_local_environment", lambda: {})

    with pytest.raises(PrivateJourneyStatusError, match="not configured"):
        PrivateJourneyStatus.from_environment()
