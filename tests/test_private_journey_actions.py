"""Synthetic-fixture tests for what the console may start, and the one gate.

Jobs run inline here so a test sees them finish. Nothing reaches Google:
the judge job is exercised only up to its gate, which is the behaviour
worth holding -- a wrong figure starts no upload.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from app.web.private_journey_actions import (
    DEFAULT_MUSIC_TRACK_ID,
    JOB_FILM,
    JOB_JUDGE,
    JOB_PREFLIGHT,
    MUSIC_TRACK_IDS,
    NO_MUSIC_TRACK_ID,
    REASON_ANOTHER_JOB_RUNNING,
    REASON_APPROVAL_MISMATCH,
    REASON_BUCKET_REQUIRED,
    REASON_CLOUD_SIGN_IN_EXPIRED,
    REASON_JOB_FAILED,
    REASON_PACKAGE_REFUSED,
    REASON_UNKNOWN_TRACK,
    STATE_DONE,
    STATE_FAILED,
    STATE_IDLE,
    STATE_RUNNING,
    JobRefused,
    PrivateJourneyJobs,
    approve_judgement,
    check_music_track,
    run_inline,
)

# --- the gate --------------------------------------------------------------------


def test_the_figure_shown_is_the_figure_approved() -> None:
    figure, bucket = approve_judgement(25.56, approve_jpy="25.56", bucket="rides")

    assert figure == 25.56
    assert bucket == "rides"


def test_a_figure_that_does_not_match_is_refused() -> None:
    for offered in ("25.5", "26", "0", "", None, "twenty-five", "25.57"):
        with pytest.raises(JobRefused) as refused:
            approve_judgement(25.56, approve_jpy=offered, bucket="rides")
        assert refused.value.reason == REASON_APPROVAL_MISMATCH
    # To the yen's hundredth: a third decimal is noise, not a different figure.
    assert approve_judgement(25.56, approve_jpy="25.561", bucket="rides")[0] == 25.56


def test_a_matching_figure_still_needs_somewhere_to_send_to() -> None:
    with pytest.raises(JobRefused) as refused:
        approve_judgement(25.56, approve_jpy=25.56, bucket="   ")
    assert refused.value.reason == REASON_BUCKET_REQUIRED


def test_the_figure_is_compared_to_the_yen_not_the_float() -> None:
    figure, _ = approve_judgement(25.556, approve_jpy="25.56", bucket="rides")
    assert figure == 25.56


def test_only_a_track_in_the_library_or_no_music_is_accepted() -> None:
    """Silence is the default and a choice; a track must be one the library has."""
    assert check_music_track(None) == DEFAULT_MUSIC_TRACK_ID == NO_MUSIC_TRACK_ID
    assert check_music_track("none") == NO_MUSIC_TRACK_ID
    assert check_music_track(" windswept ") == "windswept"
    for bad in ("../etc/passwd", "rising-tide.mp3", "x"):
        with pytest.raises(JobRefused) as refused:
            check_music_track(bad)
        assert refused.value.reason == REASON_UNKNOWN_TRACK
    assert NO_MUSIC_TRACK_ID not in MUSIC_TRACK_IDS


# --- one job at a time, and what it reports ------------------------------------


def test_nothing_is_running_at_first() -> None:
    jobs = PrivateJourneyJobs(runner=run_inline)

    assert jobs.snapshot()["state"] == STATE_IDLE


def test_a_job_runs_to_done_and_reports_only_counts(tmp_path: Path, monkeypatch) -> None:
    jobs = PrivateJourneyJobs(runner=run_inline)
    monkeypatch.setattr(
        "app.web.private_journey_actions.command_preflight",
        lambda package, *, budget_jpy, rebuild: {
            "plan": {},
            "preflight": {
                "prepared_count": 4,
                "candidate_count": 4,
                "measured_megabytes": 2.0,
                "ready": True,
                "failures": {},
            },
        },
    )

    state = jobs.start_preflight(tmp_path)

    assert state.kind == JOB_PREFLIGHT
    assert state.state == STATE_DONE
    assert state.result == {
        "prepared_count": 4,
        "candidate_count": 4,
        "measured_megabytes": 2.0,
        "ready": True,
    }
    assert jobs.snapshot()["elapsed_s"] >= 0.0


def test_a_second_job_is_refused_while_one_runs(tmp_path: Path) -> None:
    held: list = []

    def hold(target) -> None:
        held.append(target)  # never run: the job stays running

    jobs = PrivateJourneyJobs(runner=hold)
    jobs.start_film(tmp_path)
    assert jobs.current.state == STATE_RUNNING

    with pytest.raises(JobRefused) as refused:
        jobs.start_preflight(tmp_path)
    assert refused.value.reason == REASON_ANOTHER_JOB_RUNNING


def test_a_failing_job_reports_a_reason_and_never_its_message(tmp_path: Path, monkeypatch) -> None:
    def explode(package, **kwargs):
        raise RuntimeError(f"could not open {package}/secret.mp4")

    jobs = PrivateJourneyJobs(runner=run_inline)
    monkeypatch.setattr("app.web.private_journey_actions.run_private_journey_film", explode)

    state = jobs.start_film(tmp_path)

    assert state.state == STATE_FAILED
    assert state.reason == REASON_JOB_FAILED
    snapshot = jobs.snapshot()
    assert "secret" not in str(snapshot)
    assert str(tmp_path) not in str(snapshot)


def test_a_package_that_refuses_is_a_named_reason(tmp_path: Path, monkeypatch) -> None:
    from app.private_journey_film import PrivateJourneyFilmError

    def refuse(package, **kwargs):
        raise PrivateJourneyFilmError("the package is not ready to render")

    jobs = PrivateJourneyJobs(runner=run_inline)
    monkeypatch.setattr("app.web.private_journey_actions.run_private_journey_film", refuse)

    assert jobs.start_film(tmp_path).reason == REASON_PACKAGE_REFUSED


def test_an_expired_sign_in_is_its_own_reason(tmp_path: Path, monkeypatch) -> None:
    """A sign-in that has run out is not this ride refusing the request."""
    from app.analysis_cli import CloudSignInExpired

    def refuse(package, **kwargs):
        raise CloudSignInExpired("run `gcloud auth application-default login`")

    jobs = PrivateJourneyJobs(runner=run_inline)
    monkeypatch.setattr("app.web.private_journey_actions.command_judge", refuse)

    state = jobs.start_judge(tmp_path, figure_jpy=1.0, approve_jpy="1.00", bucket="rides")

    assert state.state == STATE_FAILED
    assert state.reason == REASON_CLOUD_SIGN_IN_EXPIRED


def test_the_film_job_passes_the_checked_track_through(tmp_path: Path, monkeypatch) -> None:
    seen: dict = {}

    def record(package, **kwargs):
        seen.update(kwargs)

    jobs = PrivateJourneyJobs(runner=run_inline)
    monkeypatch.setattr("app.web.private_journey_actions.run_private_journey_film", record)

    state = jobs.start_film(tmp_path, music_track_id="windswept")

    assert state.kind == JOB_FILM
    assert seen["music_track_id"] == "windswept"
    assert seen["overwrite"] is True


def test_an_unknown_track_never_starts_the_film(tmp_path: Path) -> None:
    jobs = PrivateJourneyJobs(runner=run_inline)

    with pytest.raises(JobRefused):
        jobs.start_film(tmp_path, music_track_id="../x")
    assert jobs.snapshot()["state"] == STATE_IDLE


# --- buying is gated before it is started ----------------------------------------


def test_a_wrong_figure_never_starts_the_judge_job(tmp_path: Path, monkeypatch) -> None:
    called: list = []
    monkeypatch.setattr(
        "app.web.private_journey_actions.command_judge",
        lambda *a, **k: called.append(1) or {},
    )
    jobs = PrivateJourneyJobs(runner=run_inline)

    with pytest.raises(JobRefused):
        jobs.start_judge(tmp_path, figure_jpy=25.56, approve_jpy="20", bucket="rides")

    assert called == []
    assert jobs.snapshot()["state"] == STATE_IDLE


def test_the_right_figure_starts_it_with_approval_and_the_bucket(
    tmp_path: Path, monkeypatch
) -> None:
    seen: dict = {}

    def fake_judge(package, **kwargs):
        seen.update(kwargs)
        return {"newly_bought": 3, "carried_from_earlier_attempt": 1, "plan": {}}

    monkeypatch.setattr("app.web.private_journey_actions.command_judge", fake_judge)
    jobs = PrivateJourneyJobs(runner=run_inline)

    state = jobs.start_judge(tmp_path, figure_jpy=25.56, approve_jpy=25.56, bucket=" rides ")

    assert state.kind == JOB_JUDGE
    assert state.state == STATE_DONE
    assert seen["approved"] is True
    assert seen["bucket"] == "rides"
    assert seen["overwrite"] is False
    assert state.result == {"newly_bought": 3, "carried_from_earlier_attempt": 1}


def test_buying_twice_is_a_named_reason(tmp_path: Path, monkeypatch) -> None:
    def already(package, **kwargs):
        raise FileExistsError("this package already carries a judgement")

    monkeypatch.setattr("app.web.private_journey_actions.command_judge", already)
    jobs = PrivateJourneyJobs(runner=run_inline)

    state = jobs.start_judge(tmp_path, figure_jpy=1.0, approve_jpy=1.0, bucket="rides")

    assert state.state == STATE_FAILED
    assert state.reason == "judgement_already_bought"


def test_importing_the_actions_module_reaches_no_google_library() -> None:
    import ast

    tree = ast.parse(Path("app/web/private_journey_actions.py").read_text(encoding="utf-8"))
    top_level = [n for n in tree.body if isinstance(n, (ast.Import, ast.ImportFrom))]
    names = [a.name for n in top_level if isinstance(n, ast.Import) for a in n.names] + [
        n.module or "" for n in top_level if isinstance(n, ast.ImportFrom)
    ]
    assert not any(name.startswith("google") for name in names)
