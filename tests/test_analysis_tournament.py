"""Synthetic-fixture tests for ranking a whole ride by comparison alone.

`tournament_rank` is exercised directly with synthetic (event_id, uri) pairs
and a stub comparator -- most of what makes this design cheap is the shape
of the recursion, which does not need a package, a GPX track or a proxy
clip to test. `run_tournament` and `plan_tournament_cost` are then checked
against a small synthetic package, the same fixtures `test_analysis_ranking`
uses, to confirm the wiring to `app.analysis_run`'s plan. Nothing here
reaches Google.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from app.analysis_record import BOUGHT_ANALYSIS_PROVIDERS
from app.analysis_run import PROXY_DIRECTORY_NAME, plan_analysis_run
from app.analysis_tournament import (
    DEFAULT_GROUP_SIZE,
    TOURNAMENT_RANKING_FILE_NAME,
    TOURNAMENT_RANKING_SCHEMA_VERSION,
    AnalysisTournamentError,
    TournamentRanking,
    _tournament_shape,
    load_tournament_ranking,
    plan_tournament_cost,
    run_tournament,
    tournament_rank,
    tournament_ranks_for,
    write_tournament_ranking,
)
from tests.test_analysis_ranking import _package

assert BOUGHT_ANALYSIS_PROVIDERS  # imported for the "not bought" fixtures below


def _pairs(n: int) -> list[tuple[str, str]]:
    return [(f"window-{i:03d}", f"gs://bucket/window-{i:03d}.mp4") for i in range(n)]


def _identity(pairs: list[tuple[str, str]]) -> list[str]:
    """A comparator that keeps whatever order it was handed."""
    return [event_id for event_id, _ in pairs]


def _reversed_order(pairs: list[tuple[str, str]]) -> list[str]:
    return [event_id for event_id, _ in reversed(pairs)]


def _by_true_rank(true_rank: dict[str, int]):
    def compare(pairs: list[tuple[str, str]]) -> list[str]:
        return sorted((event_id for event_id, _ in pairs), key=lambda e: true_rank[e])

    return compare


# --- the pure algorithm: shape and correctness ----------------------------------


def test_a_single_window_needs_no_comparison() -> None:
    calls: list[int] = []

    def compare(pairs):
        calls.append(len(pairs))
        return []

    assert tournament_rank(_pairs(1), compare) == ["window-000"]
    assert calls == [], "nothing to compare with"


def test_two_windows_are_one_comparison() -> None:
    order = tournament_rank(_pairs(2), _reversed_order)
    assert order == ["window-001", "window-000"]


def test_exactly_one_group_is_one_comparison() -> None:
    calls: list[int] = []

    def compare(pairs):
        calls.append(len(pairs))
        return _reversed_order(pairs)

    order = tournament_rank(_pairs(DEFAULT_GROUP_SIZE), compare, group_size=DEFAULT_GROUP_SIZE)
    assert calls == [DEFAULT_GROUP_SIZE]
    assert order == list(reversed([f"window-{i:03d}" for i in range(DEFAULT_GROUP_SIZE)]))


def test_a_true_total_order_is_recovered_when_each_groups_best_is_spread_out() -> None:
    """The approximation is exact whenever no group hides a second-best.

    Twelve windows in true-rank order, grouped by fours: the best of each
    group of four is 1st, 5th and 9th overall -- already spread one per
    group -- so comparing the three winners in the final round recovers the
    true order everywhere, not just at the top.
    """
    true_rank = {f"window-{i:03d}": i for i in range(12)}
    order = tournament_rank(_pairs(12), _by_true_rank(true_rank), group_size=4)
    assert order == [f"window-{i:03d}" for i in range(12)]


def test_the_approximation_can_rank_a_weak_window_ahead_of_a_stronger_one() -> None:
    """The documented cost of moving a whole group by its winner's placing alone.

    Window 000 is the true best and shares its group with the true worst;
    window 002 is the true second-best in the other group. Because a group's
    entire order rides on its own winner's placing in the final round, the
    true-worst window -- merely by belonging to the winning group -- is
    reported ahead of the true second- and third-best, who never left the
    weaker group. This is not a bug to fix; it is the trade the module's
    docstring describes.
    """
    true_rank = {
        "window-000": 0,  # group A's winner, true best overall
        "window-001": 5,  # group A's other member, true worst overall
        "window-002": 1,  # group B's winner, true second-best overall
        "window-003": 2,  # group B's other member, true third-best overall
    }
    order = tournament_rank(_pairs(4), _by_true_rank(true_rank), group_size=2)
    assert order == ["window-000", "window-001", "window-002", "window-003"]
    assert order.index("window-001") < order.index("window-002"), (
        "the winning group's worst window outranks the true runner-up"
    )


def test_recursion_goes_more_than_two_rounds_deep() -> None:
    """137 windows in groups of ten needs three rounds; every one is visited."""
    group_sizes_seen: list[int] = []

    def compare(pairs):
        group_sizes_seen.append(len(pairs))
        return _identity(pairs)

    order = tournament_rank(_pairs(137), compare, group_size=10)
    assert sorted(order) == sorted(f"window-{i:03d}" for i in range(137))
    assert len(order) == 137
    # Round 1: fourteen groups (thirteen of ten, one of seven). Round 2: the
    # fourteen winners, two groups. Round 3: the two group-winners of round 2.
    assert sorted(group_sizes_seen) == sorted([10] * 13 + [7] + [10, 4] + [2])


# --- resilience: a group that cannot be compared keeps its given order ---------


def test_a_group_answered_with_a_hole_is_asked_once_more() -> None:
    calls: list[int] = []

    def flaky(pairs):
        calls.append(len(pairs))
        if len(calls) == 1:
            raise RuntimeError("Vertex AI Gemini returned an incomplete ranking")
        return _reversed_order(pairs)

    order = tournament_rank(_pairs(3), flaky, group_size=3)
    assert calls == [3, 3]
    assert order == ["window-002", "window-001", "window-000"]


def test_a_group_that_cannot_be_compared_keeps_the_order_it_was_given() -> None:
    """Unlike `app.analysis_ranking`, a failed group is not dropped -- there is
    no score left to fall back on, so every window must still get a place."""

    def always_incomplete(pairs):
        return [event_id for event_id, _ in pairs][:-1]  # always drops the last label

    order = tournament_rank(_pairs(4), always_incomplete, group_size=4, attempts=2)
    assert order == ["window-000", "window-001", "window-002", "window-003"]


def test_an_error_that_is_not_a_hole_in_the_answer_is_not_swallowed() -> None:
    def broken(pairs):
        raise RuntimeError("the network went away")

    with pytest.raises(RuntimeError, match="network"):
        tournament_rank(_pairs(3), broken, group_size=3)


# --- validation ------------------------------------------------------------------


def test_a_group_smaller_than_two_is_refused() -> None:
    with pytest.raises(AnalysisTournamentError, match="between two and ten|at least two"):
        tournament_rank(_pairs(3), _identity, group_size=1)


def test_a_group_larger_than_ten_is_refused() -> None:
    with pytest.raises(AnalysisTournamentError, match="between two and ten|at least two"):
        tournament_rank(_pairs(3), _identity, group_size=11)


def test_zero_attempts_is_refused() -> None:
    with pytest.raises(AnalysisTournamentError, match="at least one attempt"):
        tournament_rank(_pairs(3), _identity, attempts=0)


def test_an_empty_tournament_is_refused() -> None:
    with pytest.raises(AnalysisTournamentError, match="at least one window"):
        tournament_rank([], _identity)


def test_the_same_window_twice_is_refused() -> None:
    with pytest.raises(AnalysisTournamentError, match="rank the same window twice"):
        tournament_rank([("a", "gs://a"), ("a", "gs://a")], _identity)


# --- the cost formula --------------------------------------------------------


def test_the_shape_matches_the_roadmap_arithmetic() -> None:
    # docs/completion-roadmap-ja.md 7.0: 173 windows in groups of ten, plus a
    # final round over the 18 winners, comes to about eleven yen.
    assert _tournament_shape(173, 10) == (193, 21)
    assert _tournament_shape(18, 10) == (20, 3)
    assert _tournament_shape(1, 10) == (0, 0)
    assert _tournament_shape(0, 10) == (0, 0)
    assert _tournament_shape(10, 10) == (10, 1)


def test_plan_tournament_cost_reads_every_candidate_not_only_the_near_equals(
    tmp_path: Path,
) -> None:
    package = _package(tmp_path / "package", recording_s=900.0)
    plan = plan_analysis_run(package)

    cost = plan_tournament_cost(package)

    windows_sent, comparisons = _tournament_shape(len(plan.candidates), DEFAULT_GROUP_SIZE)
    assert cost["windows_to_rank"] == len(plan.candidates)
    assert cost["comparisons"] == comparisons
    usd = (windows_sent * 12.0 * 100) / 1e6 * 0.30 + (comparisons * 60) / 1e6 * 2.50
    assert cost["estimated_jpy"] == round(usd * 150.0, 2)


def test_plan_tournament_cost_rejects_a_group_out_of_bounds(tmp_path: Path) -> None:
    package = _package(tmp_path / "package")
    with pytest.raises(AnalysisTournamentError, match="between two and ten"):
        plan_tournament_cost(package, group_size=1)


# --- buying and writing a full ranking --------------------------------------


def _upload(proxy: Path, event_id: str) -> str:
    return f"gs://bucket/{event_id}.mp4"


def _preflight(package: Path) -> list[str]:
    """Write a stand-in copy for every candidate, as preflight would."""
    plan = plan_analysis_run(package)
    proxies = package / PROXY_DIRECTORY_NAME
    proxies.mkdir(exist_ok=True)
    for candidate in plan.candidates:
        (proxies / f"{candidate.event_id}.mp4").write_bytes(b"copy")
    return [c.event_id for c in plan.candidates]


def test_run_tournament_ranks_every_candidate_and_writes_it_down(tmp_path: Path) -> None:
    package = _package(tmp_path / "package", recording_s=900.0)
    ids = _preflight(package)
    seen: list[int] = []

    def compare(pairs):
        seen.append(len(pairs))
        return _identity(pairs)

    path = run_tournament(package, compare=compare, upload=_upload)

    ranking = load_tournament_ranking(path)
    assert path == package / TOURNAMENT_RANKING_FILE_NAME
    assert sorted(ranking.ranks) == sorted(ids)
    assert sorted(ranking.ranks.values()) == list(range(1, len(ids) + 1))
    assert ranking.provider == "gemini"
    windows_sent, comparisons = _tournament_shape(len(ids), DEFAULT_GROUP_SIZE)
    assert sum(seen) == windows_sent
    assert len(seen) == comparisons


def test_run_tournament_falls_back_to_ride_order_when_nothing_can_be_compared(
    tmp_path: Path,
) -> None:
    package = _package(tmp_path / "package", recording_s=900.0)
    ids = _preflight(package)

    def always_broken(pairs):
        raise RuntimeError("Vertex AI Gemini returned no ranking")

    ranking = load_tournament_ranking(
        run_tournament(package, compare=always_broken, upload=_upload)
    )
    assert [event_id for event_id, _ in sorted(ranking.ranks.items(), key=lambda kv: kv[1])] == ids


def test_a_missing_copy_stops_the_tournament_before_anything_is_bought(tmp_path: Path) -> None:
    package = _package(tmp_path / "package", recording_s=900.0)
    ids = _preflight(package)
    (package / PROXY_DIRECTORY_NAME / f"{ids[0]}.mp4").unlink()
    called: list = []

    with pytest.raises(AnalysisTournamentError, match="copy is missing"):
        run_tournament(package, compare=lambda pairs: called.append(1) or [], upload=_upload)
    assert called == []


def test_a_package_already_carrying_a_ranking_is_not_overwritten_by_default(
    tmp_path: Path,
) -> None:
    package = _package(tmp_path / "package", recording_s=900.0)
    _preflight(package)
    run_tournament(package, compare=_identity, upload=_upload)

    with pytest.raises(FileExistsError, match="already carries"):
        run_tournament(package, compare=_identity, upload=_upload)
    run_tournament(package, compare=_identity, upload=_upload, overwrite=True)


def test_run_tournament_rejects_a_group_size_out_of_bounds(tmp_path: Path) -> None:
    package = _package(tmp_path / "package", recording_s=900.0)
    _preflight(package)
    with pytest.raises(AnalysisTournamentError, match="between two and ten"):
        run_tournament(package, compare=_identity, upload=_upload, group_size=1)


def test_fewer_than_two_candidates_is_nothing_to_rank(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    package = _package(tmp_path / "package", recording_s=900.0)
    _preflight(package)
    plan = plan_analysis_run(package)
    single = plan.candidates[:1]

    class _OneCandidatePlan:
        candidates = single

    monkeypatch.setattr(
        "app.analysis_tournament.plan_analysis_run", lambda *_a, **_kw: _OneCandidatePlan()
    )
    with pytest.raises(AnalysisTournamentError, match="at least two candidates"):
        run_tournament(package, compare=_identity, upload=_upload)


# --- written down, read back, and refused when not bought -----------------------


def test_a_tournament_ranking_is_read_back_and_a_stub_one_is_refused(tmp_path: Path) -> None:
    package = tmp_path / "package"
    package.mkdir()
    assert tournament_ranks_for(package) is None

    write_tournament_ranking(
        package / TOURNAMENT_RANKING_FILE_NAME,
        TournamentRanking(provider="gemini", ranks={"a": 1, "b": 2}),
    )
    assert tournament_ranks_for(package) == {"a": 1, "b": 2}

    write_tournament_ranking(
        package / TOURNAMENT_RANKING_FILE_NAME,
        TournamentRanking(provider="stub-dry-run", ranks={"a": 1}),
        overwrite=True,
    )
    with pytest.raises(AnalysisTournamentError, match="not bought"):
        tournament_ranks_for(package)


def test_a_tournament_ranking_must_be_one_to_n_without_gaps() -> None:
    with pytest.raises(ValueError, match="without gaps"):
        TournamentRanking(provider="gemini", ranks={"a": 1, "b": 3})


def test_a_tournament_ranking_needs_a_provider() -> None:
    with pytest.raises(ValueError, match="provider"):
        TournamentRanking(provider="", ranks={"a": 1})


def test_writing_a_tournament_ranking_refuses_a_symlink(tmp_path: Path) -> None:
    real = tmp_path / "real.json"
    real.write_text("{}", encoding="utf-8")
    link = tmp_path / "link.json"
    link.symlink_to(real)

    with pytest.raises(AnalysisTournamentError, match="unsafe"):
        write_tournament_ranking(link, TournamentRanking(provider="gemini", ranks={"a": 1}))


def test_writing_a_tournament_ranking_refuses_to_clobber_without_overwrite(
    tmp_path: Path,
) -> None:
    path = tmp_path / TOURNAMENT_RANKING_FILE_NAME
    write_tournament_ranking(path, TournamentRanking(provider="gemini", ranks={"a": 1}))
    with pytest.raises(FileExistsError):
        write_tournament_ranking(path, TournamentRanking(provider="gemini", ranks={"a": 1}))
    write_tournament_ranking(
        path, TournamentRanking(provider="gemini", ranks={"a": 1, "b": 2}), overwrite=True
    )
    assert json.loads(path.read_text())["ranks"] == {"a": 1, "b": 2}


def test_loading_a_tournament_ranking_refuses_a_symlink(tmp_path: Path) -> None:
    real = tmp_path / "real.json"
    write_tournament_ranking(real, TournamentRanking(provider="gemini", ranks={"a": 1}))
    link = tmp_path / "link.json"
    link.symlink_to(real)
    with pytest.raises(AnalysisTournamentError, match="unavailable"):
        load_tournament_ranking(link)


def test_loading_a_tournament_ranking_rejects_an_unsupported_schema(tmp_path: Path) -> None:
    path = tmp_path / TOURNAMENT_RANKING_FILE_NAME
    path.write_text(
        json.dumps({"schema_version": "something-else", "provider": "gemini", "ranks": {"a": 1}}),
        encoding="utf-8",
    )
    with pytest.raises(ValueError, match="unsupported"):
        load_tournament_ranking(path)


def test_from_dict_needs_its_ranks() -> None:
    with pytest.raises(ValueError, match="needs its ranks"):
        TournamentRanking.from_dict(
            {"schema_version": TOURNAMENT_RANKING_SCHEMA_VERSION, "provider": "gemini"}
        )
