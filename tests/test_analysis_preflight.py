"""Synthetic-fixture tests for preparing a run's uploads without paying.

Preflight is the half of a run that costs nothing, so these exercise it with
a stub encoder standing in only for FFmpeg -- there is no uploader and no
analyser to stub, because preflight has neither.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from app.agents import StoryOutputLanguage
from app.analysis_preflight import (
    ANALYSIS_PREFLIGHT_SCHEMA_VERSION,
    REASON_COPY_EMPTY,
    REASON_COPY_FAILED,
    REASON_SOURCE_MISSING,
    REASON_UNKNOWN_ASSET,
    PreflightFailure,
    run_preflight,
)
from app.analysis_proxy import AnalysisWindow
from app.analysis_run import (
    PROXY_DIRECTORY_NAME,
    AnalysisCandidate,
    AnalysisRunError,
    plan_analysis_run,
)
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


def _package(root: Path, *, recording_s: float = 120.0) -> Path:
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


def _encoder(size: int = 500_000):
    """Stand in for FFmpeg: write a copy of a believable size."""

    def make_proxy(window: AnalysisWindow, destination: Path) -> Path:
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_bytes(b"x" * size)
        return destination

    return make_proxy


# --- it prepares everything and measures it ---------------------------------


def test_preflight_makes_every_copy_a_run_would_send(tmp_path: Path) -> None:
    package = _package(tmp_path / "package")
    plan = plan_analysis_run(package)

    result = run_preflight(package, plan, make_proxy=_encoder())

    assert result.prepared_count == plan.candidate_count
    assert result.ready is True
    made = sorted((package / PROXY_DIRECTORY_NAME).glob("*.mp4"))
    assert len(made) == plan.candidate_count


def test_the_size_reported_is_counted_not_estimated(tmp_path: Path) -> None:
    """The approval figure had only ever been arithmetic."""
    package = _package(tmp_path / "package")
    plan = plan_analysis_run(package)

    result = run_preflight(package, plan, make_proxy=_encoder(size=500_000))

    assert result.measured_megabytes == pytest.approx(0.5 * plan.candidate_count)
    assert result.largest_megabytes == pytest.approx(0.5)


def test_the_measurement_is_compared_with_the_estimate_for_the_same_thing(
    tmp_path: Path,
) -> None:
    """Preflight makes the clips. A cascade also sends screening stills.

    Measuring one and dividing by both reads a 6% overshoot as a 22%
    saving. On the real ride that is exactly how it was first misread.
    """
    package = _package(tmp_path / "package")
    # A budget tight enough that a screening stage earns its place, so the
    # cascade total is more than the clips preflight makes.
    direct = plan_analysis_run(package)
    plan = plan_analysis_run(package, budget_jpy=direct.cascade.total_jpy / 3)
    assert plan.stills_megabytes > 0

    result = run_preflight(package, plan, make_proxy=_encoder())

    assert result.estimated_megabytes == plan.video_megabytes
    assert result.estimated_megabytes < plan.upload_megabytes
    assert result.estimated_total_megabytes == plan.upload_megabytes


def test_an_overshoot_is_not_reported_as_a_saving(tmp_path: Path) -> None:
    """What the real ride did: 95.0 MB against 89.3 MB of clips."""
    package = _package(tmp_path / "package")
    direct = plan_analysis_run(package)
    plan = plan_analysis_run(package, budget_jpy=direct.cascade.total_jpy / 3)
    # Preflight makes what the run sends, which a bound budget narrows.
    over = int(plan.video_megabytes * 1_000_000 / plan.watched_count * 1.06)

    result = run_preflight(package, plan, make_proxy=_encoder(size=over))

    assert result.measured_share_of_estimate > 1.0
    # Against the whole cascade's total it would have looked like a saving.
    assert result.measured_megabytes < result.estimated_total_megabytes


def test_each_copy_is_cut_from_its_own_window(tmp_path: Path) -> None:
    package = _package(tmp_path / "package")
    plan = plan_analysis_run(package)
    windows: list[AnalysisWindow] = []

    def make_proxy(window: AnalysisWindow, destination: Path) -> Path:
        windows.append(window)
        return _encoder()(window, destination)

    run_preflight(package, plan, make_proxy=make_proxy)

    assert [w.start_s for w in windows] == [c.start_offset_s for c in plan.candidates]


# --- it costs nothing, by construction --------------------------------------


def test_preflight_has_no_uploader_and_no_analyser_to_pass() -> None:
    """The half of a run that can be done before anyone approves a spend."""
    import inspect

    parameters = inspect.signature(run_preflight).parameters
    assert "upload" not in parameters
    assert "analyse" not in parameters


def test_importing_preflight_cannot_reach_google() -> None:
    import ast

    tree = ast.parse(Path("app/analysis_preflight.py").read_text(encoding="utf-8"))
    top_level = [node for node in tree.body if isinstance(node, (ast.Import, ast.ImportFrom))]
    names = [
        alias.name for node in top_level if isinstance(node, ast.Import) for alias in node.names
    ] + [node.module or "" for node in top_level if isinstance(node, ast.ImportFrom)]

    assert not any(name.startswith("google") for name in names)


def test_preflight_writes_no_judgement(tmp_path: Path) -> None:
    from app.analysis_record import VIDEO_ANALYSIS_RECORD_FILE_NAME

    package = _package(tmp_path / "package")
    run_preflight(package, plan_analysis_run(package), make_proxy=_encoder())

    assert not (package / VIDEO_ANALYSIS_RECORD_FILE_NAME).exists()


# --- preflight fails open where the run fails closed ------------------------


def test_one_window_that_cannot_be_copied_does_not_hide_the_rest(
    tmp_path: Path,
) -> None:
    """Stopping at the first fault answers a question nobody asked."""
    package = _package(tmp_path / "package")
    plan = plan_analysis_run(package)
    doomed = {plan.candidates[1].event_id, plan.candidates[3].event_id}

    def make_proxy(window: AnalysisWindow, destination: Path) -> Path:
        if destination.stem in doomed:
            raise RuntimeError("FFmpeg could not seek there")
        return _encoder()(window, destination)

    result = run_preflight(package, plan, make_proxy=make_proxy)

    assert result.prepared_count == plan.candidate_count - 2
    assert [f.reason for f in result.failures] == [REASON_COPY_FAILED] * 2
    assert result.ready is False


def test_a_copy_that_came_out_empty_is_a_failure_not_a_success(
    tmp_path: Path,
) -> None:
    package = _package(tmp_path / "package")
    plan = plan_analysis_run(package)

    def make_proxy(window: AnalysisWindow, destination: Path) -> Path:
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_bytes(b"")
        return destination

    result = run_preflight(package, plan, make_proxy=make_proxy)

    assert result.prepared_count == 0
    assert {f.reason for f in result.failures} == {REASON_COPY_EMPTY}


def test_a_recording_that_has_moved_is_reported_for_every_window_it_holds(
    tmp_path: Path,
) -> None:
    package = _package(tmp_path / "package")
    plan = plan_analysis_run(package)
    (package / "synthetic.mp4").unlink()

    result = run_preflight(package, plan, make_proxy=_encoder())

    assert result.ready is False
    assert {f.reason for f in result.failures} == {REASON_SOURCE_MISSING}


def test_a_window_naming_an_asset_the_catalog_lacks_is_reported(tmp_path: Path) -> None:
    from dataclasses import replace

    package = _package(tmp_path / "package")
    plan = plan_analysis_run(package)
    stranger = AnalysisCandidate(
        event_id="footage-unknown",
        asset_id="asset-unknown",
        start_offset_s=0.0,
        end_offset_s=12.0,
    )

    result = run_preflight(package, replace(plan, candidates=(stranger,)), make_proxy=_encoder())

    assert [f.reason for f in result.failures] == [REASON_UNKNOWN_ASSET]


def test_a_plan_with_nothing_to_prepare_is_refused(tmp_path: Path) -> None:
    from dataclasses import replace

    package = _package(tmp_path / "package")
    plan = plan_analysis_run(package)

    with pytest.raises(AnalysisRunError, match="nothing to prepare"):
        run_preflight(package, replace(plan, candidates=()), make_proxy=_encoder())


# --- preflighting is not wasted work ----------------------------------------


def test_a_copy_already_made_is_measured_rather_than_remade(tmp_path: Path) -> None:
    package = _package(tmp_path / "package")
    plan = plan_analysis_run(package)
    run_preflight(package, plan, make_proxy=_encoder())

    remade: list[str] = []

    def counting(window: AnalysisWindow, destination: Path) -> Path:
        remade.append(destination.name)
        return _encoder()(window, destination)

    second = run_preflight(package, plan, make_proxy=counting)

    assert remade == []
    assert second.prepared_count == plan.candidate_count


def test_rebuild_makes_them_again(tmp_path: Path) -> None:
    package = _package(tmp_path / "package")
    plan = plan_analysis_run(package)
    run_preflight(package, plan, make_proxy=_encoder())

    remade: list[str] = []

    def counting(window: AnalysisWindow, destination: Path) -> Path:
        remade.append(destination.name)
        return _encoder()(window, destination)

    run_preflight(package, plan, make_proxy=counting, rebuild=True)

    assert len(remade) == plan.candidate_count


def test_the_run_that_follows_finds_the_copies_where_it_looks(tmp_path: Path) -> None:
    """Preflight and the run agree on where a window's copy lives."""
    package = _package(tmp_path / "package")
    plan = plan_analysis_run(package)
    run_preflight(package, plan, make_proxy=_encoder())

    for candidate in plan.candidates:
        assert (package / PROXY_DIRECTORY_NAME / f"{candidate.event_id}.mp4").is_file()


# --- what the report is allowed to say --------------------------------------


def test_the_report_carries_no_private_identifier(tmp_path: Path) -> None:
    package = _package(tmp_path / "package")
    plan = plan_analysis_run(package)

    payload = run_preflight(package, plan, make_proxy=_encoder()).to_dict()
    serialized = json.dumps(payload)

    assert payload["schema_version"] == ANALYSIS_PREFLIGHT_SCHEMA_VERSION
    for forbidden in ("footage-", _ASSET_ID, "synthetic.mp4", str(tmp_path)):
        assert forbidden not in serialized


def test_failures_are_counted_by_fixed_reason_code(tmp_path: Path) -> None:
    package = _package(tmp_path / "package")
    plan = plan_analysis_run(package)
    (package / "synthetic.mp4").unlink()

    payload = run_preflight(package, plan, make_proxy=_encoder()).to_dict()

    assert payload["failures"] == {REASON_SOURCE_MISSING: plan.candidate_count}
    assert payload["ready"] is False


def test_a_failure_needs_a_reason() -> None:
    with pytest.raises(ValueError, match="needs a reason code"):
        PreflightFailure("")


def test_preflight_cuts_its_copies_from_the_copy_source(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from app import analysis_preflight

    package = _package(tmp_path / "package", recording_s=120.0)
    plan = plan_analysis_run(package)
    twin = tmp_path / "twin.lrv"
    twin.write_bytes(b"small")
    monkeypatch.setattr(analysis_preflight, "copy_source", lambda root, name: twin)
    sources: list[Path] = []

    def make_proxy(window: AnalysisWindow, destination: Path) -> Path:
        sources.append(window.source_path)
        destination.write_bytes(b"\x00" * 500_000)
        return destination

    run_preflight(package, plan, make_proxy=make_proxy)

    assert sources and all(s == twin for s in sources)
