"""Synthetic-fixture tests for the judging commands.

The one that spends money is exercised only up to the point where it
refuses, which is the behaviour worth holding: a mistyped command must not
begin an upload.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from app.agents import StoryOutputLanguage
from app.analysis_cli import (
    AnalysisCommandError,
    CloudSignInExpired,
    _is_sign_in_failure,
    _sign_in_understood,
    build_parser,
    command_judge,
    command_lifecycle_check,
    command_migrate,
    command_plan,
    command_preflight,
    command_rank,
    command_retention,
    command_screen,
    command_tournament,
    main,
)
from app.analysis_record import (
    VIDEO_ANALYSIS_RECORD_FILE_NAME,
    AnalysedEvent,
    VideoAnalysisRecord,
    write_video_analysis_record,
)
from app.analysis_run import PROXY_DIRECTORY_NAME, plan_analysis_run
from app.contracts import VideoAnalysis
from app.local_pipeline import LocalPipelineInputs
from app.video import VideoCatalog, VideoCatalogEntry

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
                asset_id="asset-synthetic-1",
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


def _judged_package(tmp_path: Path, *, recording_s: float = 900.0) -> Path:
    """A package `rank` can plan a cost for: already carries a judgement."""
    package = _package(tmp_path / "package", recording_s=recording_s)
    plan = plan_analysis_run(package)
    proxies = package / PROXY_DIRECTORY_NAME
    proxies.mkdir(exist_ok=True)
    analysed = []
    for candidate in plan.candidates:
        (proxies / f"{candidate.event_id}.mp4").write_bytes(b"copy")
        analysed.append(
            AnalysedEvent(
                event_id=candidate.event_id,
                analysis=VideoAnalysis(
                    asset_id=candidate.asset_id,
                    start_offset_s=candidate.start_offset_s,
                    end_offset_s=candidate.end_offset_s,
                    visual_description="a road",
                    road_type="highway",
                    scenery_tags=("sky",),
                    weather_visible="clear",
                    visual_interest_score=0.5,
                    story_relevance_score=0.5,
                    confidence=0.9,
                    analysis_provider="gemini",
                ),
            )
        )
    write_video_analysis_record(
        package / VIDEO_ANALYSIS_RECORD_FILE_NAME,
        VideoAnalysisRecord(tuple(analysed)),
        overwrite=True,
    )
    return package


# --- planning says what a spend would be ------------------------------------


def test_plan_reports_what_would_be_sent_and_what_it_would_cost(tmp_path: Path) -> None:
    payload = command_plan(_package(tmp_path / "package"), budget_jpy=500.0)

    assert payload["candidate_count"] > 0
    assert payload["cost"]["within_budget"] is True
    assert payload["watched_count"] == payload["candidate_count"]


def test_plan_opens_no_video(tmp_path: Path) -> None:
    """It reads catalogue metadata and the track, and nothing else."""
    package = _package(tmp_path / "package")

    command_plan(package, budget_jpy=500.0)

    assert not (package / PROXY_DIRECTORY_NAME).exists()


def test_a_package_that_cannot_be_planned_says_why(tmp_path: Path) -> None:
    with pytest.raises(AnalysisCommandError, match="no footage inside the ride"):
        command_plan(_package(tmp_path / "package", recording_s=5.0), budget_jpy=500.0)


# --- preflight prepares, and still sends nothing ----------------------------


def test_preflight_reports_the_plan_and_the_measurement(tmp_path: Path) -> None:
    package = _package(tmp_path / "package", recording_s=45.0)

    payload = command_preflight(package, budget_jpy=500.0, rebuild=False)

    assert set(payload) == {"plan", "preflight"}
    assert payload["preflight"]["candidate_count"] == payload["plan"]["watched_count"]


# --- the spending step is held back -----------------------------------------


def test_judging_without_approval_refuses_before_anything_is_uploaded(
    tmp_path: Path,
) -> None:
    with pytest.raises(AnalysisCommandError, match="--i-approve-spending"):
        command_judge(
            _package(tmp_path / "package"),
            budget_jpy=500.0,
            bucket="rides",
            prefix="",
            approved=False,
            overwrite=False,
        )


def test_judging_without_a_bucket_refuses(tmp_path: Path) -> None:
    with pytest.raises(AnalysisCommandError, match="needs --bucket"):
        command_judge(
            _package(tmp_path / "package"),
            budget_jpy=500.0,
            bucket="  ",
            prefix="",
            approved=True,
            overwrite=False,
        )


def test_a_tournament_without_approval_refuses_before_anything_is_uploaded(
    tmp_path: Path,
) -> None:
    with pytest.raises(AnalysisCommandError, match="--i-approve-spending"):
        command_tournament(
            _package(tmp_path / "package"),
            bucket="rides",
            prefix="",
            approved=False,
            overwrite=False,
        )


def test_a_tournament_without_a_bucket_refuses(tmp_path: Path) -> None:
    with pytest.raises(AnalysisCommandError, match="needs --bucket"):
        command_tournament(
            _package(tmp_path / "package"),
            bucket="  ",
            prefix="",
            approved=True,
            overwrite=False,
        )


def test_a_tournament_is_accepted_on_the_command_line() -> None:
    args = build_parser().parse_args(["tournament", "somewhere", "--bucket", "rides"])

    assert args.approved is False
    assert args.bucket == "rides"


def test_approval_is_checked_before_google_is_imported() -> None:
    """A mistyped command must not begin an upload."""
    import ast
    import inspect

    import app.analysis_cli as cli

    source = inspect.getsource(cli.command_judge)
    body = ast.parse(source.lstrip()).body[0]
    statements = [node for node in body.body if not isinstance(node, ast.Expr)]

    first_google_import = next(
        index
        for index, node in enumerate(statements)
        if isinstance(node, ast.ImportFrom) and (node.module or "").startswith("app.")
    )
    first_refusal = next(index for index, node in enumerate(statements) if isinstance(node, ast.If))
    assert first_refusal < first_google_import


def test_planning_and_preparing_import_nothing_from_google() -> None:
    import ast

    tree = ast.parse(Path("app/analysis_cli.py").read_text(encoding="utf-8"))
    top_level = [node for node in tree.body if isinstance(node, (ast.Import, ast.ImportFrom))]
    names = [
        alias.name for node in top_level if isinstance(node, ast.Import) for alias in node.names
    ] + [node.module or "" for node in top_level if isinstance(node, ast.ImportFrom)]

    assert not any(name.startswith("google") for name in names)


# --- the command line itself ------------------------------------------------


def test_approval_is_not_a_default() -> None:
    """Approving a spend is something somebody types."""
    args = build_parser().parse_args(["judge", "somewhere"])

    assert args.approved is False


def test_a_command_is_required() -> None:
    with pytest.raises(SystemExit):
        build_parser().parse_args([])


def test_main_prints_the_plan(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    package = _package(tmp_path / "package")

    main(["plan", str(package)])

    payload = json.loads(capsys.readouterr().out)
    assert payload["candidate_count"] > 0


def test_main_reports_a_refusal_rather_than_a_traceback(tmp_path: Path) -> None:
    package = _package(tmp_path / "package")

    with pytest.raises(SystemExit, match="--i-approve-spending"):
        main(["judge", str(package), "--bucket", "rides"])


def test_the_budget_can_be_lowered_from_the_command_line(tmp_path: Path) -> None:
    package = _package(tmp_path / "package", recording_s=1_800.0)

    generous = command_plan(package, budget_jpy=500.0)
    squeezed = command_plan(package, budget_jpy=generous["cost"]["total_jpy"] / 3)

    assert squeezed["watched_count"] < generous["watched_count"]
    assert squeezed["cost"]["total_jpy"] <= generous["cost"]["total_jpy"] / 3


class _RefreshError(Exception):
    """Stands in for the one Google raises when a sign-in has run out."""

    __module__ = "google.auth.exceptions"


_RefreshError.__name__ = "RefreshError"


def test_a_sign_in_that_has_run_out_says_what_to_do() -> None:
    """Not a package that refused, and not a stack of somebody else's frames."""
    with pytest.raises(CloudSignInExpired, match="application-default login"):
        with _sign_in_understood():
            raise _RefreshError("Reauthentication is needed.")


def test_a_sign_in_failure_is_recognised_under_another_error() -> None:
    """The libraries wrap it; what matters is what is underneath."""
    with pytest.raises(CloudSignInExpired):
        with _sign_in_understood():
            try:
                raise _RefreshError("Reauthentication is needed.")
            except _RefreshError as error:
                raise RuntimeError("uploading a copy failed") from error


def test_a_sign_in_that_is_fine_leaves_other_failures_alone() -> None:
    """Only this one failure is answered for; everything else passes through."""
    with pytest.raises(ValueError, match="a bucket"):
        with _sign_in_understood():
            raise ValueError("a bucket is required")


def test_an_expired_sign_in_is_a_refusal_of_the_command() -> None:
    """So the terminal prints one line, like every other refusal here."""
    assert issubclass(CloudSignInExpired, AnalysisCommandError)


# --- `rank` holds the same gate as `judge` and `tournament` -----------------


def test_ranking_without_approval_refuses_before_anything_is_uploaded(
    tmp_path: Path,
) -> None:
    with pytest.raises(AnalysisCommandError, match="--i-approve-spending"):
        command_rank(
            _package(tmp_path / "package"),
            bucket="rides",
            prefix="",
            approved=False,
            overwrite=False,
        )


def test_ranking_without_a_bucket_refuses(tmp_path: Path) -> None:
    with pytest.raises(AnalysisCommandError, match="needs --bucket"):
        command_rank(
            _package(tmp_path / "package"),
            bucket="  ",
            prefix="",
            approved=True,
            overwrite=False,
        )


def test_a_rank_command_is_accepted_on_the_command_line() -> None:
    args = build_parser().parse_args(["rank", "somewhere", "--bucket", "rides"])

    assert args.approved is False
    assert args.bucket == "rides"


# --- `command_rank`/`command_tournament` only upload a candidate they planned -----


def test_ranking_refuses_a_window_the_upload_closure_does_not_recognise(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The comparator only ever hands back event_ids `rank_windows` was given,
    but if it ever handed back something else, the closure that turns an
    event_id into an upload must say so rather than upload the wrong clip."""
    import app.analysis_cli as cli

    package = _judged_package(tmp_path)

    def _fake_rank_windows(_package, *, compare, upload, overwrite=False):
        upload(Path("proxy.mp4"), "not-a-real-event-id")
        raise AssertionError("unreachable: upload should have refused first")

    monkeypatch.setattr(cli, "rank_windows", _fake_rank_windows)
    monkeypatch.setattr("app.video.VertexAIGeminiVideoTransport", _FakeTransport)
    monkeypatch.setattr("app.analysis_adapters.rank_with", lambda *a, **k: None)
    monkeypatch.setattr("app.analysis_adapters.upload_to_bucket", lambda *a, **k: lambda *_: "")

    with pytest.raises(AnalysisCommandError, match="not in this package's plan"):
        command_rank(package, bucket="rides", prefix="", approved=True, overwrite=False)


def test_a_tournament_refuses_a_window_the_upload_closure_does_not_recognise(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import app.analysis_cli as cli

    package = _package(tmp_path / "package")

    def _fake_run_tournament(_package, *, compare, upload, overwrite=False):
        upload(Path("proxy.mp4"), "not-a-real-event-id")
        raise AssertionError("unreachable: upload should have refused first")

    monkeypatch.setattr(cli, "run_tournament", _fake_run_tournament)
    monkeypatch.setattr("app.video.VertexAIGeminiVideoTransport", _FakeTransport)
    monkeypatch.setattr("app.analysis_adapters.rank_with", lambda *a, **k: None)
    monkeypatch.setattr("app.analysis_adapters.upload_to_bucket", lambda *a, **k: lambda *_: "")

    with pytest.raises(AnalysisCommandError, match="not in this package's plan"):
        command_tournament(package, bucket="rides", prefix="", approved=True, overwrite=False)


class _FakeTransport:
    """Stands in for `VertexAIGeminiVideoTransport`; never reaches Google."""

    @staticmethod
    def from_environment() -> "_FakeTransport":
        return _FakeTransport()


# --- `screen` reads the track and sends nothing ------------------------------


def test_screen_reports_how_much_of_the_ride_stood_still(tmp_path: Path) -> None:
    package = _package(tmp_path / "package")

    payload = command_screen(package, speed_mps=1.0)

    assert payload["window_count"] > 0
    assert payload["drops_nothing"] is True


def test_screen_with_a_negative_speed_says_why(tmp_path: Path) -> None:
    with pytest.raises(AnalysisCommandError, match="cannot be negative"):
        command_screen(_package(tmp_path / "package"), speed_mps=-1.0)


def test_a_screen_command_is_accepted_on_the_command_line() -> None:
    args = build_parser().parse_args(["screen", "somewhere"])

    assert args.still_speed_mps > 0


# --- `main` dispatches every subcommand, not just `plan` and `judge` --------


def test_main_dispatches_preflight(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    package = _package(tmp_path / "package", recording_s=45.0)

    main(["preflight", str(package)])

    payload = json.loads(capsys.readouterr().out)
    assert set(payload) == {"plan", "preflight"}


def test_main_dispatches_screen(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    package = _package(tmp_path / "package")

    main(["screen", str(package)])

    json.loads(capsys.readouterr().out)  # does not raise


def test_main_reports_a_ranking_refusal_rather_than_a_traceback(tmp_path: Path) -> None:
    package = _package(tmp_path / "package")

    with pytest.raises(SystemExit, match="--i-approve-spending"):
        main(["rank", str(package), "--bucket", "rides"])


def test_main_reports_a_tournament_refusal_rather_than_a_traceback(tmp_path: Path) -> None:
    package = _package(tmp_path / "package")

    with pytest.raises(SystemExit, match="--i-approve-spending"):
        main(["tournament", str(package), "--bucket", "rides"])


# --- a refused sign-in is recognised without looping forever -----------------


def test_a_cause_cycle_does_not_loop_forever() -> None:
    """`_is_sign_in_failure` walks `__cause__`/`__context__`; a chain should
    never cycle in practice, but the walk must not hang if one somehow did."""
    first = ValueError("a")
    second = ValueError("b")
    first.__cause__ = second
    second.__cause__ = first  # a cycle back to the start

    assert _is_sign_in_failure(first) is False


def test_plan_can_fix_the_stride_into_the_package(tmp_path: Path) -> None:
    from app.analysis_cli import command_plan
    from app.analysis_run import analysis_stride_s
    from tests.test_analysis_run import _package

    package = _package(tmp_path / "package", recording_s=1_200.0)
    before = command_plan(package, budget_jpy=500.0)
    after = command_plan(package, budget_jpy=500.0, stride_s=60.0)

    assert analysis_stride_s(package) == 60.0
    assert after["candidate_count"] < before["candidate_count"]
    assert command_plan(package, budget_jpy=500.0)["candidate_count"] == after["candidate_count"]


def test_the_account_reaches_the_uploader_and_the_analyser(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """`--account` is only useful if it arrives at both ends of the spend."""
    import app.analysis_cli as cli

    package = _judged_package(tmp_path)
    seen: dict[str, object] = {}

    def _fake_rank_windows(_package, *, compare, upload, overwrite=False):
        return package / "gemini-window-ranking.json"

    monkeypatch.setattr(cli, "rank_windows", _fake_rank_windows)
    monkeypatch.setattr("app.video.VertexAIGeminiVideoTransport", _FakeTransport)
    monkeypatch.setattr(
        "app.analysis_adapters.rank_with",
        lambda *a, **k: seen.setdefault("rank_account", k.get("account_id")),
    )
    monkeypatch.setattr(
        "app.analysis_adapters.upload_to_bucket",
        lambda *a, **k: seen.setdefault("upload_account", k.get("account_id")) or (lambda *_: ""),
    )

    command_rank(
        package, bucket="rides", prefix="", approved=True, overwrite=False, account_id="rider-one"
    )

    assert seen["upload_account"] == "rider-one"
    assert seen["rank_account"] == "rider-one"


def test_no_account_leaves_the_single_rider_path_alone(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import app.analysis_cli as cli

    package = _judged_package(tmp_path)
    seen: dict[str, object] = {}

    def _fake_rank_windows(_package, *, compare, upload, overwrite=False):
        return package / "gemini-window-ranking.json"

    monkeypatch.setattr(cli, "rank_windows", _fake_rank_windows)
    monkeypatch.setattr("app.video.VertexAIGeminiVideoTransport", _FakeTransport)
    monkeypatch.setattr("app.analysis_adapters.rank_with", lambda *a, **k: None)
    monkeypatch.setattr(
        "app.analysis_adapters.upload_to_bucket",
        lambda *a, **k: seen.setdefault("account", k.get("account_id")) or (lambda *_: ""),
    )

    command_rank(package, bucket="rides", prefix="", approved=True, overwrite=False)

    assert seen["account"] is None


def test_the_account_flag_is_offered_wherever_money_is_spent() -> None:
    from app.analysis_cli import build_parser

    parser = build_parser()
    for command in ("judge", "rank", "tournament"):
        parsed = parser.parse_args([command, "package", "--account", "rider-one"])
        assert parsed.account_id == "rider-one"
        assert parser.parse_args([command, "package"]).account_id == ""


def test_a_sweep_needs_the_account_and_the_bucket_before_it_looks() -> None:
    with pytest.raises(AnalysisCommandError):
        command_retention(
            bucket="rides",
            account_id="   ",
            prefix="",
            retention_days=30,
            forget=False,
            approved=True,
        )
    with pytest.raises(AnalysisCommandError):
        command_retention(
            bucket="  ",
            account_id="rider-one",
            prefix="",
            retention_days=30,
            forget=False,
            approved=True,
        )


def test_an_unapproved_sweep_says_nothing_was_deleted(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app.retention import SweepPlan

    plan = SweepPlan(prefix="u/abcd", retention_days=30, due=("u/abcd/a.mp4",), kept=2)
    monkeypatch.setattr("app.analysis_cli.sweep", lambda *a, **k: plan)

    payload = command_retention(
        bucket="rides",
        account_id="rider-one",
        prefix="",
        retention_days=30,
        forget=False,
        approved=False,
    )

    assert payload["deleted"] == 0
    assert payload["due_for_deletion"] == 1
    assert payload["kept"] == 2
    assert "--i-approve-deletion" in str(payload["note"])


def test_a_sweep_payload_carries_counts_and_never_object_names(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app.retention import SweepPlan

    plan = SweepPlan(prefix="u/abcd", retention_days=7, due=("u/abcd/secret-window.mp4",), kept=0)
    monkeypatch.setattr("app.analysis_cli.sweep", lambda *a, **k: plan)

    payload = command_retention(
        bucket="rides",
        account_id="rider-one",
        prefix="",
        retention_days=7,
        forget=False,
        approved=True,
    )

    assert "secret-window" not in json.dumps(payload)
    assert payload["deleted"] == 1
    assert payload["forget"] is False


def test_forgetting_takes_the_forget_path_and_ignores_the_run_prefix(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app.retention import SweepPlan

    seen: dict[str, object] = {}

    def _forget(bucket: str, **kwargs: object) -> SweepPlan:
        seen.update(kwargs)
        seen["bucket"] = bucket
        return SweepPlan(prefix="u/abcd", retention_days=0, due=(), kept=0)

    monkeypatch.setattr("app.analysis_cli.forget_account", _forget)
    monkeypatch.setattr(
        "app.analysis_cli.sweep",
        lambda *a, **k: pytest.fail("forgetting must not go through the aged sweep"),
    )

    payload = command_retention(
        bucket="rides",
        account_id="rider-one",
        prefix="run-1",
        retention_days=30,
        forget=True,
        approved=True,
    )

    assert seen["bucket"] == "rides"
    assert "prefix" not in seen
    assert payload["forget"] is True


def test_a_retention_refusal_is_reported_rather_than_a_traceback(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app.retention import RetentionError

    def _refuse(*_: object, **__: object) -> None:
        raise RetentionError("a listing answered outside the prefix it was asked for")

    monkeypatch.setattr("app.analysis_cli.sweep", _refuse)

    with pytest.raises(SystemExit):
        main(["retention", "--bucket", "rides", "--account", "rider-one"])


def test_deleting_is_off_unless_it_is_typed() -> None:
    parser = build_parser()
    assert parser.parse_args(["retention", "--account", "rider-one"]).approved is False
    typed = parser.parse_args(
        ["retention", "--account", "rider-one", "--i-approve-deletion", "--forget"]
    )
    assert typed.approved is True
    assert typed.forget is True


def test_the_sweep_does_not_take_a_package() -> None:
    """What has to be deleted is what is in the bucket, not what a package remembers."""
    parser = build_parser()
    with pytest.raises(SystemExit):
        parser.parse_args(["retention", "some-package"])


def test_a_migration_needs_the_account_and_the_bucket_before_it_looks() -> None:
    with pytest.raises(AnalysisCommandError):
        command_migrate(bucket="rides", account_id="   ", approved=True)
    with pytest.raises(AnalysisCommandError):
        command_migrate(bucket="  ", account_id="rider-one", approved=True)


def test_an_unapproved_migration_says_nothing_was_moved(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app.tenant_migration import MigrationPlan, ObjectMove

    plan = MigrationPlan(
        prefix="u/abcd",
        moves=(ObjectMove(source="a.mp4", destination="u/abcd/a.mp4"),),
        already_owned=2,
        other_accounts=1,
    )
    monkeypatch.setattr("app.analysis_cli.migrate_account", lambda *a, **k: plan)

    payload = command_migrate(bucket="rides", account_id="rider-one", approved=False)

    assert payload["moved"] == 0
    assert payload["to_move"] == 1
    assert payload["already_owned"] == 2
    assert payload["other_accounts"] == 1
    assert "--i-approve-migration" in str(payload["note"])


def test_a_migration_payload_carries_counts_and_never_object_names(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app.tenant_migration import MigrationPlan, ObjectMove

    plan = MigrationPlan(
        prefix="u/abcd",
        moves=(ObjectMove(source="secret-window.mp4", destination="u/abcd/secret-window.mp4"),),
        already_owned=0,
        other_accounts=0,
    )
    monkeypatch.setattr("app.analysis_cli.migrate_account", lambda *a, **k: plan)

    payload = command_migrate(bucket="rides", account_id="rider-one", approved=True)

    assert "secret-window" not in json.dumps(payload)
    assert payload["moved"] == 1
    assert "note" not in payload


def test_a_migration_refusal_is_reported_rather_than_a_traceback(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app.tenant_migration import MigrationError

    def _refuse(*_: object, **__: object) -> None:
        raise MigrationError("an object sits in account space without an account")

    monkeypatch.setattr("app.analysis_cli.migrate_account", _refuse)

    with pytest.raises(SystemExit):
        main(["migrate", "--bucket", "rides", "--account", "rider-one"])


def test_migrating_is_off_unless_it_is_typed() -> None:
    parser = build_parser()
    assert parser.parse_args(["migrate", "--account", "rider-one"]).approved is False
    typed = parser.parse_args(["migrate", "--account", "rider-one", "--i-approve-migration"])
    assert typed.approved is True


def test_the_migration_takes_neither_a_package_nor_a_run_prefix() -> None:
    """The objects that need adopting are the ones no run and no package remembers."""
    parser = build_parser()
    with pytest.raises(SystemExit):
        parser.parse_args(["migrate", "some-package"])
    with pytest.raises(SystemExit):
        parser.parse_args(["migrate", "--account", "rider-one", "--prefix", "run-1"])


def test_a_lifecycle_check_needs_a_bucket_before_it_reads_anything() -> None:
    with pytest.raises(AnalysisCommandError):
        command_lifecycle_check(bucket="  ")


def test_a_lifecycle_check_reports_the_backstop_comparison(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app.bucket_lifecycle import BackstopCheck

    check = BackstopCheck(
        ok=True, expected_age_days=365, found_age_days=365, reason="a delete rule covers it"
    )
    monkeypatch.setattr("app.analysis_cli.evaluate_bucket_backstop", lambda *a, **k: check)

    payload = command_lifecycle_check(bucket="rides")

    assert payload == check.summary()


def test_a_lifecycle_check_refusal_is_reported_rather_than_a_traceback(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app.bucket_lifecycle import LifecycleError

    def _refuse(*_: object, **__: object) -> None:
        raise LifecycleError("a backstop check needs a bucket to look at")

    monkeypatch.setattr("app.analysis_cli.evaluate_bucket_backstop", _refuse)

    with pytest.raises(SystemExit):
        main(["lifecycle-check", "--bucket", "rides"])


def test_the_lifecycle_check_changes_nothing_so_it_has_no_approval_flag() -> None:
    """Unlike `retention` and `migrate`, there is nothing here to approve."""
    parser = build_parser()
    args = parser.parse_args(["lifecycle-check", "--bucket", "rides"])
    assert not hasattr(args, "approved")


def test_the_lifecycle_check_requires_a_bucket_on_the_command_line() -> None:
    parser = build_parser()
    with pytest.raises(SystemExit):
        parser.parse_args(["lifecycle-check"])
