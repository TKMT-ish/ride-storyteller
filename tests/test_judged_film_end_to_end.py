"""The whole judged path, from footage windows to the segments of a film.

Every piece of this chain has its own tests, and passing them all is not the
same as the chain working. This runs it: enumerate the windows a ride's
footage offers, judge them with a stub standing in for Gemini, plan the film
from that judgement, and check the cut is made from the windows the judgement
chose.

The stub is what makes this affordable to run on every commit. What it stands
in for is the one step that costs money, and everything on either side of it
is exercised for real.
"""

from __future__ import annotations

import json
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from app.agents import StoryOutputLanguage
from app.analysis_proxy import AnalysisWindow
from app.analysis_record import VIDEO_ANALYSIS_RECORD_FILE_NAME, load_video_analysis_record
from app.analysis_run import AnalysisCandidate, plan_analysis_run, run_analysis
from app.contracts import VideoAnalysis
from app.gap_chapters import GapCharacter
from app.local_pipeline import LocalPipelineInputs
from app.private_journey_film import _confirmed_footage_sources, plan_journey_film
from app.story_film import build_story_film_segments
from app.story_timeline import StoryBeatKind
from app.video import VideoCatalog, VideoCatalogEntry

_RIDE_START = datetime(2026, 5, 1, 9, 0, 0, tzinfo=UTC)
_RIDE_S = 4 * 3600.0


def _gpx(path: Path, *, point_count: int = 120) -> Path:
    step = _RIDE_S / (point_count - 1)
    points = "".join(
        '<trkpt lat="{lat:.6f}" lon="{lon:.6f}"><ele>{ele:.1f}</ele>'
        "<time>{t}</time></trkpt>".format(
            lat=35.0 + 0.002 * index,
            lon=139.0 + 0.003 * index,
            ele=100.0 + index * 4,
            t=(_RIDE_START + timedelta(seconds=step * index)).strftime("%Y-%m-%dT%H:%M:%SZ"),
        )
        for index in range(point_count)
    )
    path.write_text(
        '<?xml version="1.0" encoding="UTF-8"?><gpx version="1.1" creator="t" '
        'xmlns="http://www.topografix.com/GPX/1/1"><trk><trkseg>'
        + points
        + "</trkseg></trk></gpx>",
        encoding="utf-8",
    )
    return path


def _package(root: Path) -> Path:
    """A ride whose camera ran for two stretches, well apart."""
    root.mkdir(parents=True, exist_ok=True)
    (root / "GH010001.MP4").write_bytes(b"a recording")
    (root / "GH010002.MP4").write_bytes(b"another recording")

    inputs = LocalPipelineInputs(
        gpx_path=_gpx(root / "ride.gpx").resolve(),
        video_root=root.resolve(),
        video_to_gps_offset_s=0.0,
        target_duration_s=300.0,
        output_language=StoryOutputLanguage.JAPANESE,
    )
    (root / "local-pipeline-inputs.json").write_text(
        json.dumps(inputs.to_dict(), ensure_ascii=False), encoding="utf-8"
    )
    catalog = VideoCatalog(
        entries=(
            VideoCatalogEntry(
                asset_id="asset-a",
                file_name="GH010001.MP4",
                recorded_start_time=_RIDE_START + timedelta(seconds=1_200),
                duration_s=900.0,
            ),
            VideoCatalogEntry(
                asset_id="asset-b",
                file_name="GH010002.MP4",
                recorded_start_time=_RIDE_START + timedelta(seconds=9_000),
                duration_s=900.0,
            ),
        ),
        video_to_gps_offset_s=0.0,
    )
    (root / "local-video-catalog.json").write_text(
        json.dumps(catalog.to_dict(), ensure_ascii=False), encoding="utf-8"
    )
    return root


def _judge(favoured: set[str]):
    """Stand in for Gemini: think well of the windows named, poorly of the rest."""

    def analyse(uri: str, candidate: AnalysisCandidate) -> VideoAnalysis:
        good = candidate.event_id in favoured
        return VideoAnalysis(
            asset_id=candidate.asset_id,
            start_offset_s=candidate.start_offset_s,
            end_offset_s=candidate.end_offset_s,
            visual_description="A road" if good else "A car park",
            road_type="mountain road" if good else "car park",
            scenery_tags=("trees",) if good else ("concrete",),
            weather_visible="clear",
            visual_interest_score=0.9 if good else 0.1,
            story_relevance_score=0.9 if good else 0.1,
            confidence=0.9,
            analysis_provider="stub",
        )

    return analyse


def _upload(proxy: Path, candidate: AnalysisCandidate) -> str:
    assert proxy.exists(), "a candidate was sent without being copied down first"
    return f"gs://bucket/{candidate.event_id}.mp4"


def _proxy(window: AnalysisWindow, destination: Path) -> Path:
    """Stand in for the local copy-down: a synthetic fixture is not video."""
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_bytes(b"a small copy")
    return destination


def _run(package: Path, plan, analyse) -> Path:
    return run_analysis(
        package, plan, upload=_upload, analyse=analyse, make_proxy=_proxy, concurrency=1
    )


def test_the_whole_judged_path_runs(tmp_path: Path) -> None:
    package = _package(tmp_path / "package")

    plan = plan_analysis_run(package)
    # Half an hour of footage at a thirty-second stride, across two recordings.
    assert plan.candidate_count == 60
    assert plan.cascade.total_jpy < 500.0

    favoured = {plan.candidates[index].event_id for index in (2, 20, 40, 58)}
    _run(package, plan, _judge(favoured))

    story = plan_journey_film(package, allow_unbought_judgement=True)
    chosen = {beat.event_id for beat in story.footage_beats}

    assert chosen
    assert chosen <= favoured, "the film used a window the judgement thought poorly of"
    # A judged film opens on a few short highlights, then the first
    # chapter's card, and closes on the day's account as its last beat.
    opening = [b for b in story.beats if b.highlight]
    assert opening and story.beats[: len(opening)] == tuple(opening)
    first_card = story.beats[len(opening)]
    assert first_card.kind is StoryBeatKind.GAP_CARD and first_card.card is not None
    assert first_card.card.character not in (GapCharacter.HEADLINE, GapCharacter.CLOSE)
    closing = [
        b for b in story.beats if b.card is not None and b.card.character is GapCharacter.CLOSE
    ]
    assert len(closing) == 1 and story.beats[-1] is closing[0]


def test_the_cut_is_made_from_the_windows_the_judgement_chose(tmp_path: Path) -> None:
    package = _package(tmp_path / "package")
    plan = plan_analysis_run(package)
    favoured = {plan.candidates[index].event_id for index in (2, 40)}
    _run(package, plan, _judge(favoured))
    story = plan_journey_film(package, allow_unbought_judgement=True)

    sources = _confirmed_footage_sources(package)
    cards = tuple(tmp_path / f"card-{i}.png" for i in range(len(story.beats_with_cards)))
    for card in cards:
        card.write_bytes(b"\x89PNG")

    segments = build_story_film_segments(story, cards, sources)

    footage = [s for s in segments if s.kind is StoryBeatKind.FOOTAGE]
    assert footage
    for segment in footage:
        # Cut from the ride's own recording, at the judged window's offset.
        assert segment.input_path.suffix.upper() == ".MP4"
        assert "review-clips" not in str(segment.input_path)
        assert segment.source_start_s is not None


def test_a_judgement_that_likes_nothing_stops_before_a_film_is_planned(
    tmp_path: Path,
) -> None:
    package = _package(tmp_path / "package")
    plan = plan_analysis_run(package)
    _run(package, plan, _judge(set()))

    from app.private_journey_film import PrivateJourneyFilmError

    with pytest.raises(PrivateJourneyFilmError, match="rejected every window"):
        plan_journey_film(package, allow_unbought_judgement=True)


def test_running_twice_reads_the_judgement_rather_than_buying_it_again(
    tmp_path: Path,
) -> None:
    """Analysis is the one step that costs money."""
    package = _package(tmp_path / "package")
    plan = plan_analysis_run(package)
    _run(package, plan, _judge({plan.candidates[2].event_id}))

    calls: list[str] = []

    def counted(uri: str, candidate: AnalysisCandidate) -> VideoAnalysis:
        calls.append(candidate.event_id)
        return _judge(set())(uri, candidate)

    # Planning the film again consults the record; it never calls the analyser.
    plan_journey_film(package, allow_unbought_judgement=True)
    assert calls == []
    assert plan_analysis_run(package).already_recorded is True
    assert len(load_video_analysis_record(package / VIDEO_ANALYSIS_RECORD_FILE_NAME).analysed) == 60


def test_a_film_is_not_built_from_a_judgement_nobody_bought(tmp_path: Path) -> None:
    """A stub's scores are invented, and a film shows them as evidence.

    The record a dry run writes has the same name and the same shape as a
    bought one, and the film that comes out of it is indistinguishable.
    Nothing downstream could tell, so this is where it is caught.
    """
    from app.private_journey_film import PrivateJourneyFilmError

    package = _package(tmp_path / "package")
    plan = plan_analysis_run(package)
    _run(package, plan, _judge({plan.candidates[2].event_id}))

    with pytest.raises(PrivateJourneyFilmError, match="not bought from a model"):
        plan_journey_film(package)

    # Saying so plainly is allowed; inheriting it by default is not.
    assert plan_journey_film(package, allow_unbought_judgement=True) is not None


def test_a_bought_judgement_needs_no_permission(tmp_path: Path) -> None:
    package = _package(tmp_path / "package")
    plan = plan_analysis_run(package)

    def bought(uri: str, candidate: AnalysisCandidate) -> VideoAnalysis:
        judged = _judge({c.event_id for c in plan.candidates[::4]})(uri, candidate)
        return replace(judged, analysis_provider="gemini")

    _run(package, plan, bought)

    assert plan_journey_film(package) is not None
