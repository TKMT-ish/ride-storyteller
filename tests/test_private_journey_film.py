"""Synthetic-fixture tests for making one film from one private package."""

from __future__ import annotations

import json
import subprocess
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from app.agents import StoryOutputLanguage
from app.edit import CandidateEvidenceStatus
from app.local_pipeline import LocalPipelineInputs
from app.private_journey_film import (
    PrivateJourneyFilmError,
    _confirmed_footage_sources,
    plan_journey_film,
    run_private_journey_film,
    write_subtitle_files,
)
from app.story_film import card_raster_path
from app.story_package import JOURNEY_STORY_PLAN_FILE_NAME, load_journey_story_plan
from app.story_timeline import StoryBeatKind
from app.video import (
    LocalEvidenceDecision,
    LocalEvidenceReview,
    LocalReviewClip,
    ResolvedCandidateClip,
    VideoCatalog,
    VideoCatalogEntry,
    VideoMatchStatus,
    export_candidate_json,
    write_local_evidence_review,
    write_local_review_clip_manifest,
)

_ASSET_ID = "asset-synthetic-1"
_ASSET_START = datetime(2026, 5, 1, 9, 0, 0, tzinfo=UTC)
_OFFSET_S = 0.0
# Two 30 s clips plus three cards capped at 12 s can reach 96 s, so this
# target is attainable and the duration gate is exercised rather than
# permanently failed.
_TARGET_S = 90.0
# The camera ran for these windows, measured from the asset's start.
_CLIP_WINDOWS = ((1_800.0, 1_830.0), (5_400.0, 5_430.0))


def _gpx(path: Path, *, point_count: int = 60, span_s: float = 7_200.0) -> Path:
    """A ride that heads north-east for two hours."""
    step = span_s / (point_count - 1)
    points = []
    for index in range(point_count):
        moment = _ASSET_START + timedelta(seconds=step * index)
        points.append(
            '<trkpt lat="{lat:.6f}" lon="{lon:.6f}"><ele>{ele:.1f}</ele>'
            "<time>{time}</time></trkpt>".format(
                lat=35.0 + 0.0005 * index,
                lon=139.0 + 0.0009 * index,
                ele=100.0 + index,
                time=moment.strftime("%Y-%m-%dT%H:%M:%SZ"),
            )
        )
    path.write_text(
        '<?xml version="1.0" encoding="UTF-8"?>\n'
        '<gpx version="1.1" creator="test" xmlns="http://www.topografix.com/GPX/1/1">'
        "<trk><trkseg>" + "".join(points) + "</trkseg></trk></gpx>",
        encoding="utf-8",
    )
    return path


def _clip(event_id: str, window: tuple[float, float]) -> ResolvedCandidateClip:
    return ResolvedCandidateClip(
        chapter_id=f"chapter_{event_id}",
        event_id=event_id,
        status=VideoMatchStatus.MATCHED,
        asset_id=_ASSET_ID,
        file_name="synthetic.mp4",
        start_offset_s=window[0],
        end_offset_s=window[1],
        reason="synthetic match",
    )


def _package(root: Path, *, statuses: dict[str, CandidateEvidenceStatus] | None = None) -> Path:
    root.mkdir(parents=True, exist_ok=True)
    clips = tuple(_clip(f"evt_{index}", window) for index, window in enumerate(_CLIP_WINDOWS))
    statuses = statuses or {clip.event_id: CandidateEvidenceStatus.CONFIRMED for clip in clips}

    inputs = LocalPipelineInputs(
        gpx_path=_gpx(root / "ride.gpx").resolve(),
        video_root=root.resolve(),
        video_to_gps_offset_s=_OFFSET_S,
        target_duration_s=_TARGET_S,
        output_language=StoryOutputLanguage.JAPANESE,
    )
    (root / "local-pipeline-inputs.json").write_text(
        json.dumps(inputs.to_dict(), ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    catalog = VideoCatalog(
        entries=(
            VideoCatalogEntry(
                asset_id=_ASSET_ID,
                file_name="synthetic.mp4",
                recorded_start_time=_ASSET_START,
                duration_s=7_200.0,
            ),
        ),
        video_to_gps_offset_s=_OFFSET_S,
    )
    (root / "local-video-catalog.json").write_text(
        json.dumps(catalog.to_dict(), ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    (root / "ride-storyteller-candidates.json").write_text(
        export_candidate_json(clips), encoding="utf-8"
    )
    write_local_evidence_review(
        root / "evidence-review.json",
        LocalEvidenceReview(
            tuple(
                LocalEvidenceDecision(
                    event_id=clip.event_id,
                    evidence_status=statuses[clip.event_id],
                    evidence_source=(
                        None
                        if statuses[clip.event_id]
                        is CandidateEvidenceStatus.AWAITING_VIDEO_EVIDENCE
                        else "synthetic_decision"
                    ),
                )
                for clip in clips
            )
        ),
        overwrite=True,
    )
    review_clips = tuple(
        LocalReviewClip(
            event_id=clip.event_id,
            asset_id=_ASSET_ID,
            output_file_name=f"review-{index + 1:03d}.mp4",
            duration_s=30.0,
        )
        for index, clip in enumerate(clips)
    )
    write_local_review_clip_manifest(
        root / "review-clip-manifest.json", review_clips, overwrite=True
    )
    clip_directory = root / "review-clips"
    clip_directory.mkdir(exist_ok=True)
    for review_clip in review_clips:
        (clip_directory / review_clip.output_file_name).write_bytes(b"synthetic clip")
    # The film is cut from the ride's own recording, so the catalogued source
    # file has to exist under the video root as well as its review proxy.
    (root / "synthetic.mp4").write_bytes(b"synthetic source recording")
    return root


def _drawing_runner(package: Path):
    """Stand in for Quick Look: one PNG for every page named in the command.

    qlmanage draws any number of pages in one call, and an animated card is
    a run of pages, so the stand-in must draw them all.
    """

    def run(command, **_kwargs):
        for argument in command:
            if str(argument).endswith(".html"):
                card_raster_path(Path(argument), package / "story-cards").write_bytes(b"\x89PNG")
        return subprocess.CompletedProcess(list(command), 0, "", "")

    return run


def _film_runner(package: Path, output_file_name: str):
    """FFmpeg writes where the command points, which is a partial file."""

    def runner(command, **_kwargs) -> subprocess.CompletedProcess[str]:
        Path(command[-1]).write_bytes(b"film")
        return subprocess.CompletedProcess(args=(), returncode=0, stdout="", stderr="")

    return runner


# --- planning ---------------------------------------------------------------


def test_planning_writes_the_film_shape_into_the_package(tmp_path: Path) -> None:
    package = _package(tmp_path / "package")

    plan = plan_journey_film(package)

    assert (package / JOURNEY_STORY_PLAN_FILE_NAME).is_file()
    assert load_journey_story_plan(package / JOURNEY_STORY_PLAN_FILE_NAME) == plan


def test_the_plan_runs_from_departure_to_arrival(tmp_path: Path) -> None:
    """The ride starts and ends unfilmed, so cards must bracket the footage."""
    plan = plan_journey_film(_package(tmp_path / "package"))

    assert plan.beats[0].kind is StoryBeatKind.GAP_CARD
    assert plan.beats[-1].kind is StoryBeatKind.GAP_CARD
    assert len(plan.footage_beats) == len(_CLIP_WINDOWS)


def test_footage_is_placed_by_the_window_the_camera_filmed(tmp_path: Path) -> None:
    """Not by the GPS event window, which is far shorter."""
    plan = plan_journey_film(_package(tmp_path / "package"))

    assert plan.footage_screen_duration_s == pytest.approx(
        sum(end - start for start, end in _CLIP_WINDOWS)
    )


def test_only_confirmed_clips_reach_the_film(tmp_path: Path) -> None:
    package = _package(
        tmp_path / "package",
        statuses={
            "evt_0": CandidateEvidenceStatus.CONFIRMED,
            "evt_1": CandidateEvidenceStatus.REJECTED,
        },
    )

    plan = plan_journey_film(package)

    assert [beat.event_id for beat in plan.footage_beats] == ["evt_0"]


def test_a_package_with_nothing_confirmed_cannot_be_planned(tmp_path: Path) -> None:
    package = _package(
        tmp_path / "package",
        statuses={
            "evt_0": CandidateEvidenceStatus.REJECTED,
            "evt_1": CandidateEvidenceStatus.REJECTED,
        },
    )

    with pytest.raises(PrivateJourneyFilmError, match="no confirmed clip"):
        plan_journey_film(package)


# --- subtitles --------------------------------------------------------------


def test_subtitles_are_named_to_match_the_film(tmp_path: Path) -> None:
    package = _package(tmp_path / "package")
    plan = plan_journey_film(package)

    names = write_subtitle_files(package, plan, film_file_name="my-film.mp4")

    assert names == ("my-film.srt", "my-film.vtt")
    assert (package / "my-film.srt").read_text(encoding="utf-8").startswith("1\n")
    assert (package / "my-film.vtt").read_text(encoding="utf-8").startswith("WEBVTT")


def test_subtitles_say_what_the_cards_say(tmp_path: Path) -> None:
    package = _package(tmp_path / "package")
    plan = plan_journey_film(package)

    write_subtitle_files(package, plan, film_file_name="film.mp4")

    srt = (package / "film.srt").read_text(encoding="utf-8")
    assert plan.card_beats[0].card.title in srt


# --- the whole run ----------------------------------------------------------


def test_one_call_produces_the_film_and_its_subtitles(tmp_path: Path) -> None:
    package = _package(tmp_path / "package")

    result = run_private_journey_film(
        package,
        card_runner=_drawing_runner(package),
        film_runner=_film_runner(package, "ride-storyteller-story-film.mp4"),
    )

    assert result.film.footage_segment_count == len(_CLIP_WINDOWS)
    plan = load_journey_story_plan(package / JOURNEY_STORY_PLAN_FILE_NAME)
    assert result.film.card_segment_count == len(plan.card_beats)
    assert result.plan_beat_count == len(plan.beats)
    assert result.plan_total_screen_duration_s == pytest.approx(plan.total_screen_duration_s)
    assert result.subtitle_file_names == (
        "ride-storyteller-story-film.srt",
        "ride-storyteller-story-film.vtt",
    )
    assert (package / "ride-storyteller-story-film.mp4").is_file()


def test_the_run_reports_only_safe_aggregates(tmp_path: Path) -> None:
    package = _package(tmp_path / "package")

    result = run_private_journey_film(
        package,
        card_runner=_drawing_runner(package),
        film_runner=_film_runner(package, "ride-storyteller-story-film.mp4"),
    )
    serialized = json.dumps(result.to_dict(), ensure_ascii=False)

    assert result.to_dict()["external_data_sent"] is False
    assert result.to_dict()["local_only"] is True
    for forbidden in ("evt_", _ASSET_ID, "synthetic.mp4", str(package), "2026-05-01"):
        assert forbidden not in serialized


def test_gate_one_is_binding(tmp_path: Path) -> None:
    """A package Gate 1 will not pass is never rendered."""
    package = _package(
        tmp_path / "package",
        statuses={
            "evt_0": CandidateEvidenceStatus.CONFIRMED,
            "evt_1": CandidateEvidenceStatus.AWAITING_VIDEO_EVIDENCE,
        },
    )

    with pytest.raises(PrivateJourneyFilmError, match="evidence_awaiting_present"):
        run_private_journey_film(package, card_runner=_drawing_runner(package))

    assert not (package / "ride-storyteller-story-film.mp4").exists()
    # Unsettled evidence stops the run before anything is even planned.
    assert not (package / JOURNEY_STORY_PLAN_FILE_NAME).exists()


def test_the_film_is_not_replaced_by_accident(tmp_path: Path) -> None:
    package = _package(tmp_path / "package")
    (package / "ride-storyteller-story-film.mp4").write_bytes(b"earlier")

    with pytest.raises(FileExistsError):
        run_private_journey_film(
            package,
            card_runner=_drawing_runner(package),
            film_runner=_film_runner(package, "ride-storyteller-story-film.mp4"),
        )


def test_a_judged_package_takes_its_sources_from_the_judged_windows(
    tmp_path: Path,
) -> None:
    """Reading the old export would look up clips the plan no longer names."""
    package = _package(tmp_path / "package")
    _write_analysis(package, {"evt_0": 0.9})

    sources = _confirmed_footage_sources(package)

    assert set(sources) == {"evt_0"}
    assert sources["evt_0"].path.name == "synthetic.mp4"


def test_the_film_is_cut_from_the_recording_not_the_review_proxy(tmp_path: Path) -> None:
    """Review proxies are 720p; the ride's own footage is what ships."""
    package = _package(tmp_path / "package")
    plan = plan_journey_film(package)

    sources = _confirmed_footage_sources(package)

    assert set(sources) == {beat.event_id for beat in plan.footage_beats}
    for event_id, source in sources.items():
        assert source.path.name == "synthetic.mp4"
        assert "review-clips" not in str(source.path)
    # Each source window starts where the resolved clip does.
    assert sorted(source.start_s for source in sources.values()) == sorted(
        start for start, _ in _CLIP_WINDOWS
    )


def test_a_recording_that_has_moved_stops_the_cut(tmp_path: Path) -> None:
    package = _package(tmp_path / "package")
    (package / "synthetic.mp4").unlink()

    with pytest.raises(PrivateJourneyFilmError, match="no longer where it was"):
        _confirmed_footage_sources(package)


def test_a_catalogued_name_that_is_a_path_is_refused(tmp_path: Path) -> None:
    from app.private_journey_film import _source_recording

    with pytest.raises(PrivateJourneyFilmError, match="must not be a path"):
        _source_recording(tmp_path, "../escape.mp4")


# ---------------------------------------------------------------------------
# Judgements deciding the film
#
# The point of paying Gemini to look at footage is that its answer changes
# which clips are used. A package without a record must still cut a film.
# ---------------------------------------------------------------------------


def _write_analysis(root: Path, scores: dict[str, float], *, confidence: float = 0.9) -> None:
    from app.analysis_record import (
        VIDEO_ANALYSIS_RECORD_FILE_NAME,
        AnalysedEvent,
        VideoAnalysisRecord,
        write_video_analysis_record,
    )
    from app.contracts import VideoAnalysis

    write_video_analysis_record(
        root / VIDEO_ANALYSIS_RECORD_FILE_NAME,
        VideoAnalysisRecord(
            tuple(
                AnalysedEvent(
                    event_id=event_id,
                    analysis=VideoAnalysis(
                        asset_id=_ASSET_ID,
                        start_offset_s=0.0,
                        end_offset_s=30.0,
                        visual_description="A road",
                        road_type="road",
                        scenery_tags=("sky",),
                        weather_visible="clear",
                        visual_interest_score=score,
                        story_relevance_score=score,
                        confidence=confidence,
                        analysis_provider="gemini",
                    ),
                )
                for event_id, score in scores.items()
            )
        ),
    )


def test_without_a_judgement_every_confirmed_clip_is_used(tmp_path: Path) -> None:
    package = _package(tmp_path / "package")

    plan = plan_journey_film(package)

    assert len(plan.footage_beats) == len(_CLIP_WINDOWS)


def test_a_judgement_decides_which_clips_the_film_uses(tmp_path: Path) -> None:
    package = _package(tmp_path / "package")
    _write_analysis(package, {"evt_0": 0.9, "evt_1": 0.05})

    plan = plan_journey_film(package)

    assert [beat.event_id for beat in plan.footage_beats if not beat.highlight] == ["evt_0"]


def test_an_unsure_judgement_keeps_a_clip_out(tmp_path: Path) -> None:
    package = _package(tmp_path / "package")
    _write_analysis(package, {"evt_0": 0.9, "evt_1": 0.9}, confidence=0.05)

    with pytest.raises(PrivateJourneyFilmError, match="rejected every window"):
        plan_journey_film(package)


def test_a_record_that_cannot_be_read_stops_the_plan(tmp_path: Path) -> None:
    """Falling back would cut a different film from the one paid to be judged."""
    from app.analysis_record import VIDEO_ANALYSIS_RECORD_FILE_NAME, VideoAnalysisRecordError

    package = _package(tmp_path / "package")
    (package / VIDEO_ANALYSIS_RECORD_FILE_NAME).write_text("{not json", encoding="utf-8")

    with pytest.raises(VideoAnalysisRecordError, match="unreadable"):
        plan_journey_film(package)
