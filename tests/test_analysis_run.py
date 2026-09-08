"""Synthetic-fixture tests for planning and running a paid judgement."""

from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from app.agents import StoryOutputLanguage
from app.analysis_proxy import AnalysisWindow
from app.analysis_record import (
    VIDEO_ANALYSIS_RECORD_FILE_NAME,
    load_video_analysis_record,
)
from app.analysis_run import (
    ANALYSIS_RUN_SCHEMA_VERSION,
    PARTIAL_RECORD_FILE_NAME,
    PROXY_DIRECTORY_NAME,
    AnalysisCandidate,
    AnalysisRunError,
    plan_analysis_run,
    run_analysis,
)
from app.contracts import VideoAnalysis
from app.local_pipeline import LocalPipelineInputs
from app.video import VideoCatalog, VideoCatalogEntry

_ASSET_ID = "asset-synthetic-1"
_RIDE_START = datetime(2026, 5, 1, 9, 0, 0, tzinfo=UTC)


def _gpx(path: Path, *, span_s: float = 4 * 3600.0, point_count: int = 60) -> Path:
    step = span_s / (point_count - 1)
    points = "".join(
        '<trkpt lat="{lat:.6f}" lon="{lon:.6f}"><ele>100</ele><time>{t}</time></trkpt>'.format(
            lat=35.0 + 0.001 * index,
            lon=139.0 + 0.001 * index,
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


def _package(root: Path, *, recording_s: float = 1_200.0) -> Path:
    """A package whose camera ran for one stretch inside the ride."""
    root.mkdir(parents=True, exist_ok=True)
    (root / "synthetic.mp4").write_bytes(b"a recording")
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
                asset_id=_ASSET_ID,
                file_name="synthetic.mp4",
                recorded_start_time=_RIDE_START + timedelta(seconds=600),
                duration_s=recording_s,
            ),
        ),
        video_to_gps_offset_s=0.0,
    )
    (root / "local-video-catalog.json").write_text(
        json.dumps(catalog.to_dict(), ensure_ascii=False), encoding="utf-8"
    )
    return root


def _analysis(score: float = 0.8) -> VideoAnalysis:
    return VideoAnalysis(
        asset_id=_ASSET_ID,
        start_offset_s=0.0,
        end_offset_s=12.0,
        visual_description="A road",
        road_type="road",
        scenery_tags=("sky",),
        weather_visible="clear",
        visual_interest_score=score,
        story_relevance_score=score,
        confidence=0.9,
        analysis_provider="gemini",
    )


# --- planning sends nothing -------------------------------------------------


def test_planning_reports_what_would_be_sent_and_what_it_would_cost(tmp_path: Path) -> None:
    plan = plan_analysis_run(_package(tmp_path / "package"))

    # Twenty minutes of footage at a thirty-second stride.
    assert plan.candidate_count == 40
    assert plan.upload_megabytes > 0
    assert plan.cascade.total_jpy > 0
    assert plan.cascade.to_dict()["within_budget"] is True


def test_planning_draws_candidates_from_the_footage_not_from_gps_events(
    tmp_path: Path,
) -> None:
    """Seven events against a camera that ran for half the ride."""
    plan = plan_analysis_run(_package(tmp_path / "package", recording_s=1_800.0))

    assert plan.candidate_count == 60


def test_judging_a_whole_ride_stays_far_under_the_ceiling(tmp_path: Path) -> None:
    plan = plan_analysis_run(_package(tmp_path / "package"), budget_jpy=500.0)

    assert plan.cascade.total_jpy < 50.0
    assert plan.cascade.tightened is False


def test_a_package_whose_camera_never_ran_in_the_ride_is_refused(tmp_path: Path) -> None:
    with pytest.raises(AnalysisRunError, match="no footage inside the ride"):
        plan_analysis_run(_package(tmp_path / "package", recording_s=5.0))


def test_planning_says_whether_the_judgement_was_already_bought(tmp_path: Path) -> None:
    package = _package(tmp_path / "package")
    assert plan_analysis_run(package).already_recorded is False

    (package / VIDEO_ANALYSIS_RECORD_FILE_NAME).write_text("{}", encoding="utf-8")
    assert plan_analysis_run(package).already_recorded is True


def test_the_plan_carries_no_private_identifier(tmp_path: Path) -> None:
    payload = plan_analysis_run(_package(tmp_path / "package")).to_dict()
    serialized = json.dumps(payload)

    assert payload["schema_version"] == ANALYSIS_RUN_SCHEMA_VERSION
    for forbidden in ("footage-", _ASSET_ID, "synthetic.mp4", str(tmp_path)):
        assert forbidden not in serialized


def test_a_budget_that_cannot_be_met_is_reported_as_such(tmp_path: Path) -> None:
    with pytest.raises(AnalysisRunError, match="no cascade fits"):
        plan_analysis_run(_package(tmp_path / "package"), budget_jpy=0.000001)


# --- running needs the means handed to it -----------------------------------


def _proxy(window: AnalysisWindow, destination: Path) -> Path:
    """Stand in for the local copy-down: a synthetic fixture is not video."""
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_bytes(b"a small copy")
    return destination


def _uploader(seen: list[str]):
    def upload(proxy: Path, candidate: AnalysisCandidate) -> str:
        seen.append(candidate.event_id)
        return f"gs://bucket/{candidate.event_id}.mp4"

    return upload


def _run(package: Path, plan, **kwargs) -> Path:
    kwargs.setdefault("upload", _uploader([]))
    kwargs.setdefault("analyse", lambda uri, candidate: _analysis())
    kwargs.setdefault("make_proxy", _proxy)
    # Sequential by default here: the resumption tests count exactly what a
    # fault leaves behind, and that count is only exact one at a time.
    kwargs.setdefault("concurrency", 1)
    return run_analysis(package, plan, **kwargs)


def test_a_run_judges_every_candidate_and_writes_the_record(tmp_path: Path) -> None:
    package = _package(tmp_path / "package", recording_s=120.0)
    plan = plan_analysis_run(package)
    uploaded: list[str] = []

    path = _run(package, plan, upload=_uploader(uploaded))

    record = load_video_analysis_record(path)
    assert len(uploaded) == plan.candidate_count
    assert len(record.analysed) == plan.candidate_count
    assert record.analysis_for(plan.candidates[0].event_id) is not None


def test_the_analyser_reads_what_the_uploader_returned(tmp_path: Path) -> None:
    package = _package(tmp_path / "package", recording_s=60.0)
    plan = plan_analysis_run(package)
    seen: list[str] = []

    def analyse(uri: str, candidate: AnalysisCandidate) -> VideoAnalysis:
        seen.append(uri)
        return _analysis()

    _run(package, plan, analyse=analyse)

    assert seen == [f"gs://bucket/{c.event_id}.mp4" for c in plan.candidates]


def test_a_candidate_that_was_not_uploaded_is_never_judged(tmp_path: Path) -> None:
    package = _package(tmp_path / "package", recording_s=60.0)
    plan = plan_analysis_run(package)

    with pytest.raises(AnalysisRunError, match="not uploaded before being judged"):
        _run(package, plan, upload=lambda proxy, candidate: "")


def test_a_failing_candidate_stops_the_run_rather_than_being_skipped(
    tmp_path: Path,
) -> None:
    """A record missing a judgement would cut a different film, silently."""
    package = _package(tmp_path / "package", recording_s=90.0)
    plan = plan_analysis_run(package)

    doomed = plan.candidates[1].event_id

    def analyse(uri: str, candidate: AnalysisCandidate) -> VideoAnalysis:
        if candidate.event_id == doomed:
            raise RuntimeError("the model refused")
        return _analysis()

    with pytest.raises(RuntimeError, match="the model refused"):
        _run(package, plan, analyse=analyse)

    assert not (package / VIDEO_ANALYSIS_RECORD_FILE_NAME).exists()


def test_a_candidate_naming_an_unknown_asset_stops_the_run(tmp_path: Path) -> None:
    package = _package(tmp_path / "package", recording_s=45.0)
    plan = plan_analysis_run(package)
    stranger = AnalysisCandidate(
        event_id="footage-unknown",
        asset_id="asset-unknown",
        start_offset_s=0.0,
        end_offset_s=12.0,
    )
    from dataclasses import replace

    with pytest.raises(AnalysisRunError, match="asset the catalog lacks"):
        _run(package, replace(plan, candidates=(stranger,)))


def test_buying_a_judgement_twice_needs_saying_so(tmp_path: Path) -> None:
    package = _package(tmp_path / "package", recording_s=60.0)
    plan = plan_analysis_run(package)
    _run(package, plan)

    with pytest.raises(FileExistsError, match="already carries a judgement"):
        _run(package, plan)


def test_nothing_here_can_spend_money_by_being_called() -> None:
    """Both the uploader and the analyser are required, with no defaults."""
    import inspect

    parameters = inspect.signature(run_analysis).parameters
    for name in ("upload", "analyse"):
        assert parameters[name].default is inspect.Parameter.empty


def test_a_small_ride_is_not_starved_by_a_budget_it_never_strained(
    tmp_path: Path,
) -> None:
    """Narrowing here fits a budget; choosing clips is a later, separate job.

    A cascade tuned for two hundred candidates leaves one clip out of seven,
    which is not a film -- and the budget was never the constraint.
    """
    plan = plan_analysis_run(_package(tmp_path / "package"), budget_jpy=500.0)

    assert plan.cascade.final_candidate_count == plan.candidate_count
    assert plan.cascade.tightened is False
    assert plan.cascade.total_jpy < 500.0


def test_a_binding_budget_still_narrows_what_is_sent(tmp_path: Path) -> None:
    plan = plan_analysis_run(_package(tmp_path / "package"), budget_jpy=0.5)

    assert plan.cascade.tightened is True
    assert plan.cascade.total_jpy <= 0.5


# --- what leaves the machine is the small copy, never the ride's own file ----


def test_what_is_uploaded_is_the_small_copy_and_never_the_original(
    tmp_path: Path,
) -> None:
    """The originals are 68.1 GiB. Sending one would be the whole problem."""
    package = _package(tmp_path / "package", recording_s=60.0)
    plan = plan_analysis_run(package)
    original = (package / "synthetic.mp4").resolve()
    sent: list[Path] = []

    def upload(proxy: Path, candidate: AnalysisCandidate) -> str:
        sent.append(proxy)
        return "gs://bucket/clip.mp4"

    _run(package, plan, upload=upload)

    assert sent
    for proxy in sent:
        assert proxy.resolve() != original
        assert proxy.parent == package / PROXY_DIRECTORY_NAME


def test_each_candidate_is_copied_down_from_its_own_window(tmp_path: Path) -> None:
    package = _package(tmp_path / "package", recording_s=60.0)
    plan = plan_analysis_run(package)
    windows: list[AnalysisWindow] = []

    def make_proxy(window: AnalysisWindow, destination: Path) -> Path:
        windows.append(window)
        return _proxy(window, destination)

    _run(package, plan, make_proxy=make_proxy)

    assert [w.start_s for w in windows] == [c.start_offset_s for c in plan.candidates]
    assert all(w.source_path.name == "synthetic.mp4" for w in windows)


def test_the_copies_are_kept_so_a_rerun_need_not_rebuild_them(tmp_path: Path) -> None:
    package = _package(tmp_path / "package", recording_s=60.0)
    plan = plan_analysis_run(package)

    _run(package, plan)

    kept = sorted((package / PROXY_DIRECTORY_NAME).glob("*.mp4"))
    assert len(kept) == plan.candidate_count


def test_a_recording_that_has_moved_stops_the_run(tmp_path: Path) -> None:
    """Judging a window of a file that is gone would buy nothing."""
    package = _package(tmp_path / "package", recording_s=60.0)
    plan = plan_analysis_run(package)
    (package / "synthetic.mp4").unlink()

    with pytest.raises(AnalysisRunError, match="no longer where it was"):
        _run(package, plan)


def test_making_the_copy_is_local_and_free_so_it_has_a_real_default() -> None:
    """Unlike the two steps that leave the machine."""
    import inspect

    from app.analysis_proxy import write_proxy_clip

    parameters = inspect.signature(run_analysis).parameters
    assert parameters["make_proxy"].default is write_proxy_clip


# --- a screening stage is planned only when it earns its place --------------


def _stage_names(plan) -> list[str]:
    return [stage.name for stage in plan.cascade.stages]


def test_a_budget_that_does_not_bind_plans_no_screening_stage(tmp_path: Path) -> None:
    """Keeping everything, screening screens nothing and still bills.

    It also made the plan describe a run that `run_analysis` does not
    perform: the run sends one clip per candidate and asks once.
    """
    plan = plan_analysis_run(_package(tmp_path / "package"), budget_jpy=500.0)

    assert _stage_names(plan) == ["already-matched", "gemini-video"]
    assert plan.stills_megabytes == 0.0
    assert plan.cascade.final_candidate_count == plan.candidate_count


def test_screening_appears_when_the_direct_cascade_would_be_tightened(
    tmp_path: Path,
) -> None:
    """A cheap look at everything beats not looking at most of it."""
    package = _package(tmp_path / "package", recording_s=1_800.0)
    direct = plan_analysis_run(package, budget_jpy=500.0)
    assert "gemini-stills" not in _stage_names(direct)

    squeezed = plan_analysis_run(package, budget_jpy=direct.cascade.total_jpy / 3)

    assert "gemini-stills" in _stage_names(squeezed)
    assert squeezed.stills_megabytes > 0


def test_screening_looks_at_more_candidates_than_the_watching_stage(
    tmp_path: Path,
) -> None:
    package = _package(tmp_path / "package", recording_s=1_800.0)
    direct = plan_analysis_run(package, budget_jpy=500.0)

    squeezed = plan_analysis_run(package, budget_jpy=direct.cascade.total_jpy / 3)

    stages = {stage.name: stage for stage in squeezed.cascade.stages}
    assert stages["gemini-stills"].candidates_in > stages["gemini-video"].candidates_in


def test_dropping_the_idle_screening_stage_lowers_what_is_quoted(
    tmp_path: Path,
) -> None:
    """On the real ride this was 32 MB and a third of the cost, buying nothing."""
    plan = plan_analysis_run(_package(tmp_path / "package"), budget_jpy=500.0)

    only_clips = plan.video_megabytes
    assert plan.upload_megabytes == pytest.approx(only_clips)


def test_the_quoted_upload_is_what_the_run_actually_sends(tmp_path: Path) -> None:
    """One clip per candidate, and nothing else."""
    package = _package(tmp_path / "package", recording_s=60.0)
    plan = plan_analysis_run(package)
    sent: list[Path] = []

    def upload(proxy: Path, candidate: AnalysisCandidate) -> str:
        sent.append(proxy)
        return "gs://bucket/clip.mp4"

    _run(package, plan, upload=upload)

    assert len(sent) == plan.candidate_count
    assert plan.stills_megabytes == 0.0


# --- a run bills no more than the plan somebody approved --------------------


def _squeezed(package: Path):
    """A plan whose budget binds, so the cascade prices fewer than it found."""
    direct = plan_analysis_run(package, budget_jpy=500.0)
    return plan_analysis_run(package, budget_jpy=direct.cascade.total_jpy / 3)


def test_a_narrowed_plan_judges_only_what_it_pays_for(tmp_path: Path) -> None:
    """Judging the rest anyway bills past what somebody approved.

    On one real ride, a 20 yen ceiling prices 86 windows at 15.0 yen while
    judging all 173 costs 25.6 -- over the ceiling that was agreed to.
    """
    package = _package(tmp_path / "package", recording_s=1_800.0)
    plan = _squeezed(package)
    assert plan.watched_count < plan.candidate_count

    judged: list[str] = []

    def analyse(uri: str, candidate: AnalysisCandidate) -> VideoAnalysis:
        judged.append(candidate.event_id)
        return _analysis()

    _run(package, plan, analyse=analyse)

    assert len(judged) == plan.watched_count


def test_a_narrowed_run_still_sees_the_whole_ride(tmp_path: Path) -> None:
    """Taking the first 86 would buy the first half and none of the second."""
    package = _package(tmp_path / "package", recording_s=1_800.0)
    plan = _squeezed(package)

    positions = [plan.candidates.index(c) for c in plan.watched_candidates]

    gaps = {b - a for a, b in zip(positions, positions[1:], strict=False)}

    assert positions[0] == 0
    assert max(gaps) - min(gaps) <= 1, "the ride is sampled unevenly"
    # The tail left over is no longer than the spacing itself: the last
    # window chosen is near the end of the ride, not near its middle.
    assert plan.candidate_count - 1 - positions[-1] <= max(gaps)


def test_a_plan_that_does_not_bind_still_judges_everything(tmp_path: Path) -> None:
    package = _package(tmp_path / "package", recording_s=120.0)
    plan = plan_analysis_run(package, budget_jpy=500.0)

    assert plan.watched_candidates == plan.candidates
    assert plan.watched_count == plan.candidate_count


def test_preflight_prepares_only_what_the_run_will_send(tmp_path: Path) -> None:
    """Encoding the rest is minutes spent on files nobody uploads."""
    from app.analysis_preflight import run_preflight

    package = _package(tmp_path / "package", recording_s=1_800.0)
    plan = _squeezed(package)

    result = run_preflight(package, plan, make_proxy=_proxy)

    assert result.prepared_count == plan.watched_count
    assert result.prepared_count < len(plan.candidates)


def test_the_plan_reports_how_many_it_pays_for(tmp_path: Path) -> None:
    package = _package(tmp_path / "package", recording_s=1_800.0)

    payload = _squeezed(package).to_dict()

    assert payload["watched_count"] < payload["candidate_count"]


# --- a run that breaks part-way keeps what it paid for ----------------------


def test_a_run_that_fails_part_way_keeps_the_judgements_it_bought(
    tmp_path: Path,
) -> None:
    """173 windows is 173 billed calls; a fault at the 150th must not lose 149."""
    package = _package(tmp_path / "package", recording_s=300.0)
    plan = plan_analysis_run(package)
    doomed = plan.candidates[5].event_id
    asked: list[str] = []

    def flaky(uri: str, candidate: AnalysisCandidate) -> VideoAnalysis:
        asked.append(candidate.event_id)
        if candidate.event_id == doomed:
            raise RuntimeError("the network went away")
        return _analysis()

    with pytest.raises(RuntimeError, match="the network went away"):
        _run(package, plan, analyse=flaky)

    assert not (package / VIDEO_ANALYSIS_RECORD_FILE_NAME).exists()
    kept = load_video_analysis_record(package / PARTIAL_RECORD_FILE_NAME)
    assert len(kept.analysed) == 5


def test_a_rerun_asks_only_about_what_it_does_not_have(tmp_path: Path) -> None:
    package = _package(tmp_path / "package", recording_s=300.0)
    plan = plan_analysis_run(package)
    doomed = plan.candidates[5].event_id

    def flaky(uri: str, candidate: AnalysisCandidate) -> VideoAnalysis:
        if candidate.event_id == doomed:
            raise RuntimeError("the network went away")
        return _analysis()

    with pytest.raises(RuntimeError):
        _run(package, plan, analyse=flaky)

    asked_again: list[str] = []

    def steady(uri: str, candidate: AnalysisCandidate) -> VideoAnalysis:
        asked_again.append(candidate.event_id)
        return _analysis()

    _run(package, plan, analyse=steady)

    # The five already bought are not bought a second time.
    assert len(asked_again) == plan.watched_count - 5
    assert doomed in asked_again


def test_the_running_total_is_removed_once_the_real_record_exists(
    tmp_path: Path,
) -> None:
    package = _package(tmp_path / "package", recording_s=60.0)

    _run(package, plan_analysis_run(package))

    assert (package / VIDEO_ANALYSIS_RECORD_FILE_NAME).exists()
    assert not (package / PARTIAL_RECORD_FILE_NAME).exists()


def test_a_completed_run_holds_every_judgement_including_the_carried_ones(
    tmp_path: Path,
) -> None:
    package = _package(tmp_path / "package", recording_s=300.0)
    plan = plan_analysis_run(package)
    doomed = plan.candidates[5].event_id

    def flaky(uri: str, candidate: AnalysisCandidate) -> VideoAnalysis:
        if candidate.event_id == doomed:
            raise RuntimeError("the network went away")
        return _analysis()

    with pytest.raises(RuntimeError):
        _run(package, plan, analyse=flaky)
    path = _run(package, plan)

    record = load_video_analysis_record(path)
    assert len(record.analysed) == plan.watched_count
    assert [item.event_id for item in record.analysed] == [
        candidate.event_id for candidate in plan.watched_candidates
    ]


def test_an_unreadable_running_total_is_not_silently_rebought(tmp_path: Path) -> None:
    """Starting over quietly would buy the whole ride a second time."""
    package = _package(tmp_path / "package", recording_s=60.0)
    plan = plan_analysis_run(package)
    (package / PARTIAL_RECORD_FILE_NAME).write_text("not json", encoding="utf-8")

    with pytest.raises(AnalysisRunError, match="unreadable part-finished judgement"):
        _run(package, plan)


# --- several judgements in flight at once --------------------------------------


def test_judging_in_parallel_returns_the_record_in_plan_order(tmp_path: Path) -> None:
    import threading
    import time

    package = _package(tmp_path / "package", recording_s=600.0)
    plan = plan_analysis_run(package)
    seen_threads: set[int] = set()

    def slow(uri: str, candidate: AnalysisCandidate) -> VideoAnalysis:
        seen_threads.add(threading.get_ident())
        time.sleep(0.01)
        return _analysis()

    path = _run(package, plan, analyse=slow, concurrency=4)

    record = load_video_analysis_record(path)
    assert [item.event_id for item in record.analysed] == [
        c.event_id for c in plan.watched_candidates
    ]
    assert len(seen_threads) > 1, "nothing ran in parallel"


def test_a_fault_in_parallel_keeps_what_finished_and_buys_nothing_twice(
    tmp_path: Path,
) -> None:
    package = _package(tmp_path / "package", recording_s=600.0)
    plan = plan_analysis_run(package)
    doomed = plan.candidates[3].event_id

    def flaky(uri: str, candidate: AnalysisCandidate) -> VideoAnalysis:
        if candidate.event_id == doomed:
            raise RuntimeError("the network went away")
        return _analysis()

    with pytest.raises(RuntimeError):
        _run(package, plan, analyse=flaky, concurrency=4)

    kept = {
        i.event_id for i in load_video_analysis_record(package / PARTIAL_RECORD_FILE_NAME).analysed
    }
    assert doomed not in kept
    assert kept, "nothing that finished was kept"

    asked: list[str] = []

    def steady(uri: str, candidate: AnalysisCandidate) -> VideoAnalysis:
        asked.append(candidate.event_id)
        return _analysis()

    _run(package, plan, analyse=steady, concurrency=4)

    assert not (set(asked) & kept), "a judgement already paid for was bought again"
    assert doomed in asked


def test_a_run_needs_at_least_one_in_flight(tmp_path: Path) -> None:
    package = _package(tmp_path / "package", recording_s=60.0)
    with pytest.raises(AnalysisRunError, match="at least one"):
        _run(package, plan_analysis_run(package), concurrency=0)


def test_the_default_runs_several_at_once() -> None:
    import inspect

    from app.analysis_run import DEFAULT_CONCURRENCY

    assert DEFAULT_CONCURRENCY > 1
    assert inspect.signature(run_analysis).parameters["concurrency"].default == DEFAULT_CONCURRENCY


def test_a_rerun_with_a_new_window_buys_only_that_window(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A finished record is what was paid for; a turn window added later is all that is bought."""
    from app import analysis_run
    from app.gps.turns import SharpTurn

    package = _package(tmp_path / "package", recording_s=300.0)
    first = plan_analysis_run(package)
    _run(package, first)

    # The track now proves a corner 20 s into the recording, between windows.
    corner_at = _RIDE_START + timedelta(seconds=600 + 20)
    monkeypatch.setattr(
        analysis_run,
        "sharp_turns",
        lambda points: (
            SharpTurn(corner_at - timedelta(seconds=3), corner_at + timedelta(seconds=3), 120.0),
        ),
    )
    second = plan_analysis_run(package)
    assert len(second.candidates) == len(first.candidates) + 1

    asked: list[str] = []

    def counting(uri: str, candidate: AnalysisCandidate) -> VideoAnalysis:
        asked.append(candidate.event_id)
        return _analysis()

    path = _run(package, second, analyse=counting, overwrite=True)

    new = {c.event_id for c in second.candidates} - {c.event_id for c in first.candidates}
    assert set(asked) == new, "only the new window was bought"
    assert len(load_video_analysis_record(path).analysed) == second.watched_count


def test_a_package_can_fix_its_stride_so_every_plan_agrees(tmp_path: Path) -> None:
    from app.analysis_run import (
        ANALYSIS_SETTINGS_FILE_NAME,
        analysis_stride_s,
        write_analysis_settings,
    )

    package = _package(tmp_path / "package", recording_s=1_200.0)
    default = plan_analysis_run(package)
    assert analysis_stride_s(package) == 30.0

    write_analysis_settings(package, stride_s=60.0)

    assert (package / ANALYSIS_SETTINGS_FILE_NAME).is_file()
    assert analysis_stride_s(package) == 60.0
    wider = plan_analysis_run(package)
    assert 0 < len(wider.candidates) < len(default.candidates), "half the stride, half the windows"
    assert plan_analysis_run(package, stride_s=30.0).candidate_count == default.candidate_count
    with pytest.raises(AnalysisRunError):
        write_analysis_settings(package, stride_s=0.0)


def test_the_copy_is_cut_from_the_cameras_own_proxy_when_it_has_one(tmp_path: Path) -> None:
    from app.analysis_run import copy_source, source_recording

    root = tmp_path / "footage"
    root.mkdir()
    (root / "GX010042.MP4").write_bytes(b"4k")
    assert copy_source(root, "GX010042.MP4") == root / "GX010042.MP4", "no proxy: the original"

    (root / "GL010042.LRV").write_bytes(b"small")
    assert copy_source(root, "GX010042.MP4") == root / "GL010042.LRV"
    assert source_recording(root, "GX010042.MP4") == root / "GX010042.MP4", (
        "the film keeps the original"
    )
