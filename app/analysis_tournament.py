"""Rank every window by comparison alone, and never buy a per-window verdict.

`app.analysis_run` pays for a verdict on each candidate on its own, and
`app.analysis_ranking` then pays again to tell the near-equals apart. On a
173-window ride that is about ¥25.6 to judge plus a few yen to rank --
most of the bill is the first pass, and the film only ever reads the score
back to decide an order. Gate 7's price bands do not leave room for that
first pass at all: ¥100 a month for four rides affords ¥7.5 a ride, and
judging alone already costs more (see `docs/completion-roadmap-ja.md`,
7.0).

So this throws the first pass away and keeps only the second. No window is
ever asked "how good is this on its own" -- every question put to the model
is "which of these ten belongs in the film more". Comparisons are grouped
the same way `app.analysis_ranking` groups its near-equals (at most ten
clips in one request, a comparison the model can actually hold), but here
every candidate the ride has takes part, not just the ones already tied by
a score that was never bought.

Producing one order over more candidates than fit in a group needs more
than one round. Each round's groups are compared, and the winner of every
group -- the one thing this design still trusts a single comparison to
settle -- goes forward into a smaller round of the same shape, recursively,
until a round is small enough to compare in one request. The final order is
each round's winner-order read backwards into the group orders it stood
for: first, the groups in the order their winners placed; within each
group, the order the group itself was given.

That is an approximation -- the seventh-best window in the strongest group
never gets compared against the third-best in the weakest one -- and it is
the one this design is willing to make, in exchange for a cost that grows
with the log of the ride rather than its length. Measured against the
roadmap's own arithmetic: 173 windows in groups of ten is 18 first-round
comparisons plus a handful more to place the 18 winners, near ¥11 against
¥27.9 for judge-then-rank (`plan_tournament_cost` below reproduces that
figure from the same per-second rate `app.analysis_ranking` uses).

What this does not buy back: `app.gemini_selection` also reads a
`VideoAnalysis` for things no comparison answers -- whether the rider fills
the frame, whether a window sits in a car park, whether the bike ever
moved, which family of road it shows. A ride ranked this way has none of
that, because nothing here ever asked the model to describe a window, only
to compare it. The decision this module used to leave open is made now:
`select_judged_candidates(..., requires_analysis=False)` (and
`app.story_pacing.select_by_chapter` alongside it) stops treating a missing
`VideoAnalysis` as a reason to drop a candidate, so a tournament's `ranks`
alone can carry a ride through selection and pacing -- both of which were
already rank-shaped underneath the score. What is lost by taking that path
is real, not merely theoretical: none of the filters above run, so a
tournament-only film can show a window `select_judged_candidates`'s ordinary
floors would have refused. That trade has not been decided for production;
this only makes it possible to measure, which is what the next unit does
against real material rather than guessing at the size of the gap.

Nothing here imports Google; the comparator and uploader are handed in,
exactly as `app.analysis_ranking` takes them.
"""

from __future__ import annotations

import json
import os
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from tempfile import mkstemp

from app.analysis_record import BOUGHT_ANALYSIS_PROVIDERS
from app.analysis_run import PROXY_DIRECTORY_NAME, plan_analysis_run

TOURNAMENT_RANKING_FILE_NAME = "gemini-tournament-ranking.json"
TOURNAMENT_RANKING_SCHEMA_VERSION = "gemini-tournament-ranking-v1"

# Same ceiling as `app.analysis_ranking`: Vertex AI refuses an eleventh clip
# in one request, and ten is already under a yen a group.
DEFAULT_GROUP_SIZE = 10
MAX_GROUP_SIZE = 10


class AnalysisTournamentError(RuntimeError):
    """Raised when a full ranking cannot be bought or read as asked."""


# A comparator is handed the ordered (event_id, uri) pairs of one group and
# returns the event_ids best first. It is the only thing here that spends.
Comparator = Callable[[list[tuple[str, str]]], list[str]]


@dataclass(frozen=True)
class TournamentRanking:
    """A full order over one ride's candidates, 1 = most deserves a place."""

    provider: str
    ranks: Mapping[str, int]

    def __post_init__(self) -> None:
        if not self.provider:
            raise ValueError("a ranking needs a provider")
        values = sorted(self.ranks.values())
        if values != list(range(1, len(values) + 1)):
            raise ValueError("a ranking must number its windows 1..n without gaps")

    def to_dict(self) -> dict[str, object]:
        return {
            "schema_version": TOURNAMENT_RANKING_SCHEMA_VERSION,
            "provider": self.provider,
            "ranks": dict(sorted(self.ranks.items(), key=lambda item: item[1])),
        }

    @classmethod
    def from_dict(cls, payload: Mapping[str, object]) -> "TournamentRanking":
        if payload.get("schema_version") != TOURNAMENT_RANKING_SCHEMA_VERSION:
            raise ValueError("unsupported tournament ranking schema")
        ranks = payload.get("ranks")
        if not isinstance(ranks, Mapping):
            raise ValueError("a tournament ranking needs its ranks")
        return cls(
            provider=str(payload.get("provider", "")),
            ranks={str(k): int(v) for k, v in ranks.items()},  # type: ignore[arg-type]
        )


def write_tournament_ranking(
    path: Path, ranking: TournamentRanking, *, overwrite: bool = False
) -> Path:
    if path.is_symlink():
        raise AnalysisTournamentError("the ranking path is unsafe")
    if path.exists() and not overwrite:
        raise FileExistsError("this package already carries a tournament ranking")
    path.parent.mkdir(parents=True, exist_ok=True)
    handle, temporary = mkstemp(dir=path.parent, prefix=".tournament-", suffix=".json")
    try:
        with os.fdopen(handle, "w", encoding="utf-8") as stream:
            json.dump(ranking.to_dict(), stream, ensure_ascii=False, indent=2)
        os.replace(temporary, path)
    except BaseException:
        Path(temporary).unlink(missing_ok=True)
        raise
    return path


def load_tournament_ranking(path: Path) -> TournamentRanking:
    if path.is_symlink() or not path.is_file():
        raise AnalysisTournamentError("the tournament ranking is unavailable")
    return TournamentRanking.from_dict(json.loads(path.read_text(encoding="utf-8")))


def tournament_ranks_for(package_directory: Path) -> Mapping[str, int] | None:
    """The bought tournament ranking, or None when the package has none.

    Same refusal as `app.analysis_ranking.ranks_for`: a ranking that cannot
    be read is an error, not a silent absence, because a film cut without
    it is a different film and nobody would see it happen.
    """
    path = package_directory / TOURNAMENT_RANKING_FILE_NAME
    if not path.exists():
        return None
    ranking = load_tournament_ranking(path)
    if ranking.provider not in BOUGHT_ANALYSIS_PROVIDERS:
        raise AnalysisTournamentError("this ranking was not bought from a model")
    return ranking.ranks


def tournament_rank(
    pairs: Sequence[tuple[str, str]],
    compare: Comparator,
    *,
    group_size: int = DEFAULT_GROUP_SIZE,
    attempts: int = 2,
) -> list[str]:
    """The full order over `pairs`, best first, built from grouped comparisons alone.

    Every event_id in `pairs` appears exactly once, in a group of at most
    `group_size`. A group's own order comes straight from `compare`; where
    there is more than one group, each group's winner is carried into a
    smaller round of the same shape, and the round's answer over the
    winners becomes the order the groups are read out in.

    A group `compare` cannot answer -- a dropped or invented label, twice in
    a row -- is not thrown away, unlike `app.analysis_ranking.rank_windows`.
    There, a group's absence from the ranking still leaves a score for
    selection to fall back on; here there is no score at all, so a group
    that cannot be compared keeps the order it was handed (ride order, or
    whatever order an earlier round gave its members) rather than vanishing
    from the film's account of the ride entirely.
    """
    if not 2 <= group_size <= MAX_GROUP_SIZE:
        raise AnalysisTournamentError("a group is between two and ten windows")
    if attempts < 1:
        raise AnalysisTournamentError("a comparison needs at least one attempt")
    ids = [event_id for event_id, _ in pairs]
    if not ids:
        raise AnalysisTournamentError("a tournament needs at least one window")
    if len(set(ids)) != len(ids):
        raise AnalysisTournamentError("a tournament cannot rank the same window twice")
    return _tournament_order(list(pairs), compare, group_size=group_size, attempts=attempts)


def _tournament_order(
    pairs: list[tuple[str, str]],
    compare: Comparator,
    *,
    group_size: int,
    attempts: int,
) -> list[str]:
    if len(pairs) <= group_size:
        return _group_order(pairs, compare, attempts=attempts)

    lookup = dict(pairs)
    groups = [pairs[start : start + group_size] for start in range(0, len(pairs), group_size)]
    group_orders = [_group_order(group, compare, attempts=attempts) for group in groups]
    representatives = [(order[0], lookup[order[0]]) for order in group_orders]
    winner_order = _tournament_order(
        representatives, compare, group_size=group_size, attempts=attempts
    )
    order_by_winner = {order[0]: order for order in group_orders}
    result: list[str] = []
    for winner in winner_order:
        result.extend(order_by_winner[winner])
    return result


def _group_order(group: list[tuple[str, str]], compare: Comparator, *, attempts: int) -> list[str]:
    """One group's order, best first; the group's own order if it cannot be compared."""
    ids = [event_id for event_id, _ in group]
    if len(group) <= 1:
        return ids
    for _ in range(attempts):
        try:
            order = list(compare(group))
        except Exception as error:  # noqa: BLE001 - the transport's own error class is not imported here
            if not _is_incomplete_answer(error):
                raise
            continue
        if sorted(order) == sorted(ids):
            return order
    return ids


def _is_incomplete_answer(error: Exception) -> bool:
    """A model answer with a hole in it, as the transport reports it; nothing else is swallowed."""
    text = str(error).lower()
    return "incomplete ranking" in text or "returned no ranking" in text


def run_tournament(
    package_directory: Path,
    *,
    compare: Comparator,
    upload: Callable[[Path, str], str],
    group_size: int = DEFAULT_GROUP_SIZE,
    provider: str = "gemini",
    overwrite: bool = False,
    attempts: int = 2,
    stride_s: float | None = None,
) -> Path:
    """Buy a full ranking of every candidate in this package, and write it down.

    Replaces `app.analysis_run.run_analysis` and `app.analysis_ranking.rank_windows`
    together for a ride taking this cheaper path: no candidate is judged on
    its own, so there is no `VideoAnalysisRecord` to write, only an order.
    The copies already made by preflight are what get sent; nothing is
    re-encoded.
    """
    if not 2 <= group_size <= MAX_GROUP_SIZE:
        raise AnalysisTournamentError("a group is between two and ten windows")
    destination = package_directory / TOURNAMENT_RANKING_FILE_NAME
    if destination.exists() and not overwrite:
        raise FileExistsError(
            "this package already carries a tournament ranking; pass overwrite=True"
        )

    plan = plan_analysis_run(package_directory, stride_s=stride_s)
    if len(plan.candidates) < 2:
        raise AnalysisTournamentError("a tournament needs at least two candidates")

    proxies = package_directory / PROXY_DIRECTORY_NAME
    pairs: list[tuple[str, str]] = []
    for candidate in plan.candidates:
        proxy = proxies / f"{candidate.event_id}.mp4"
        if not proxy.is_file() or proxy.is_symlink():
            raise AnalysisTournamentError("a window's copy is missing; run preflight first")
        pairs.append((candidate.event_id, upload(proxy, candidate.event_id)))

    order = tournament_rank(pairs, compare, group_size=group_size, attempts=attempts)
    ranks = {event_id: rank for rank, event_id in enumerate(order, start=1)}
    return write_tournament_ranking(
        destination, TournamentRanking(provider=provider, ranks=ranks), overwrite=True
    )


def plan_tournament_cost(
    package_directory: Path,
    *,
    group_size: int = DEFAULT_GROUP_SIZE,
    stride_s: float | None = None,
) -> dict[str, object]:
    """What a tournament would send and roughly cost. Sends nothing.

    Same per-second rate `app.analysis_ranking.plan_ranking_cost` prices a
    comparison at; the difference is that every candidate takes part, in
    however many rounds it takes to place them all, rather than only the
    windows a bought judgement left near the cut.
    """
    if not 2 <= group_size <= MAX_GROUP_SIZE:
        raise AnalysisTournamentError("a group is between two and ten windows")
    plan = plan_analysis_run(package_directory, stride_s=stride_s)
    windows_sent, comparisons = _tournament_shape(len(plan.candidates), group_size)
    seconds_each = plan.candidates[0].duration_s if plan.candidates else 12.0
    # Low-resolution video: about 100 tokens a second; a short ordered answer.
    input_tokens = int(windows_sent * seconds_each * 100)
    output_tokens = comparisons * 60
    usd = input_tokens / 1e6 * 0.30 + output_tokens / 1e6 * 2.50
    return {
        "windows_to_rank": len(plan.candidates),
        "comparisons": comparisons,
        "estimated_jpy": round(usd * 150.0, 2),
    }


def _tournament_shape(candidate_count: int, group_size: int) -> tuple[int, int]:
    """How many windows a tournament would send in total, and in how many requests.

    A candidate that ends a round alone (a group of one, or a single
    finalist) is never sent to the model at all -- there is nothing to
    compare it against -- so it counts toward neither total. Mirrors
    `_tournament_order`'s recursion exactly, without calling anyone.
    """
    if candidate_count <= 1:
        return 0, 0
    if candidate_count <= group_size:
        return candidate_count, 1
    groups = [
        min(group_size, candidate_count - start) for start in range(0, candidate_count, group_size)
    ]
    windows_sent = sum(size for size in groups if size > 1)
    comparisons = sum(1 for size in groups if size > 1)
    winners = len(groups)
    more_windows, more_comparisons = _tournament_shape(winners, group_size)
    return windows_sent + more_windows, comparisons + more_comparisons
