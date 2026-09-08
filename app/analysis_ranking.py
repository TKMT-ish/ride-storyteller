"""Ask the model to compare the windows it scored alike, and keep its order.

Scoring one window at a time gives every window a number and nothing to
measure it against, and on two real rides the numbers came back bunched:
most of a ride at 0.6, none of it told apart. A rubric widened that a
little. What actually separates two windows the model called "0.6" is to
show it both and ask which one belongs in the film.

So this is a second, cheap pass over the top of the judgement. The windows
whose score sits within a band of the best are taken, in groups of at most
ten, and each group goes to the model in one request -- all its clips
attached, labelled A, B, C -- with the question: order these by how much
each deserves a place in a five-minute film of this ride. What comes back
is an order, and that order is written down beside the judgement.

Selection reads it as the first tie-breaker. The heuristics -- a kind of
road not yet shown, distance from what is taken -- still order whatever
the model was not asked about. The model's own comparison beats a guess,
but only where it was actually asked.

Cost is small by construction: ten twelve-second copies are about
fourteen thousand input tokens and an answer of a few dozen, under one yen
a group. The ranking is bought once and read back after, like the
judgement. Nothing here imports Google; the comparator is handed in.
"""

from __future__ import annotations

import json
import os
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from tempfile import mkstemp

from app.analysis_record import (
    BOUGHT_ANALYSIS_PROVIDERS,
    VIDEO_ANALYSIS_RECORD_FILE_NAME,
    load_video_analysis_record,
)
from app.analysis_run import PROXY_DIRECTORY_NAME, plan_analysis_run
from app.gemini_selection import DEFAULT_INTEREST_WEIGHT, DEFAULT_STORY_WEIGHT

WINDOW_RANKING_FILE_NAME = "gemini-window-ranking.json"
WINDOW_RANKING_SCHEMA_VERSION = "gemini-window-ranking-v1"

# Windows scoring within this much of the selection's cut are worth
# telling apart. The cut, not the best: on the first real ride the six
# windows near the top were ranked and the film did not move, because the
# decision is made at the twentieth place, where thirty windows sat at
# exactly 0.66. Rank where the decision is.
DEFAULT_RANK_BAND = 0.05
# About how many footage windows a five-minute film takes (240 s / 12 s).
DEFAULT_SLOTS = 20
# Four groups of ten: a couple of yen, and enough to cover a wide tie.
DEFAULT_MAX_WINDOWS = 40
# Vertex AI accepts at most ten video files in one request (measured: a
# twelfth is refused). Ten is also under a yen a group.
DEFAULT_GROUP_SIZE = 10
MAX_GROUP_SIZE = 10

RANKING_PROMPT = (
    "These are windows from one day's motorcycle ride, each about twelve seconds, "
    "labelled Window A, Window B and so on. A five-minute film of the ride has room "
    "for only some of them. Order ALL of the labels from the window that most "
    "deserves a place in that film to the one that least deserves it. Prefer "
    "windows that show the character of the ride -- scenery, curves, a climb or "
    "descent, a change of terrain or weather, a landmark, a departure or arrival -- "
    "over windows where little changes. Use only what is visible. Return every "
    "label exactly once."
)


class AnalysisRankingError(RuntimeError):
    """Raised when the windows cannot be ranked as asked."""


# A comparator is handed the ordered (event_id, uri) pairs of one group and
# returns the event_ids best first. It is the only thing here that spends.
Comparator = Callable[[list[tuple[str, str]]], list[str]]


@dataclass(frozen=True)
class WindowRanking:
    """The model's order over the windows it was asked about, 1 = best."""

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
            "schema_version": WINDOW_RANKING_SCHEMA_VERSION,
            "provider": self.provider,
            "ranks": dict(sorted(self.ranks.items(), key=lambda item: item[1])),
        }

    @classmethod
    def from_dict(cls, payload: Mapping[str, object]) -> "WindowRanking":
        if payload.get("schema_version") != WINDOW_RANKING_SCHEMA_VERSION:
            raise ValueError("unsupported window ranking schema")
        ranks = payload.get("ranks")
        if not isinstance(ranks, Mapping):
            raise ValueError("a window ranking needs its ranks")
        return cls(
            provider=str(payload.get("provider", "")),
            ranks={str(k): int(v) for k, v in ranks.items()},  # type: ignore[arg-type]
        )


def write_window_ranking(path: Path, ranking: WindowRanking, *, overwrite: bool = False) -> Path:
    if path.is_symlink():
        raise AnalysisRankingError("the ranking path is unsafe")
    if path.exists() and not overwrite:
        raise FileExistsError("this package already carries a ranking")
    path.parent.mkdir(parents=True, exist_ok=True)
    handle, temporary = mkstemp(dir=path.parent, prefix=".ranking-", suffix=".json")
    try:
        with os.fdopen(handle, "w", encoding="utf-8") as stream:
            json.dump(ranking.to_dict(), stream, ensure_ascii=False, indent=2)
        os.replace(temporary, path)
    except BaseException:
        Path(temporary).unlink(missing_ok=True)
        raise
    return path


def load_window_ranking(path: Path) -> WindowRanking:
    if path.is_symlink() or not path.is_file():
        raise AnalysisRankingError("the ranking is unavailable")
    return WindowRanking.from_dict(json.loads(path.read_text(encoding="utf-8")))


def windows_worth_ranking(
    package_directory: Path,
    *,
    band: float = DEFAULT_RANK_BAND,
    slots: int = DEFAULT_SLOTS,
    max_windows: int = DEFAULT_MAX_WINDOWS,
    interest_weight: float = DEFAULT_INTEREST_WEIGHT,
    story_weight: float = DEFAULT_STORY_WEIGHT,
) -> list[str]:
    """The judged windows around the selection's cut, best first.

    Everything from the top down to `band` below the score at the last
    slot is worth comparing, because that is the stretch where a tie
    decides what is in the film and what is not. Capped so a wide tie
    costs a few yen rather than many.

    Reads the bought judgement only. A judgement no model was paid for is
    refused here as everywhere: ranking invented scores would be theatre.
    """
    if band < 0:
        raise AnalysisRankingError("a band cannot be negative")
    if slots < 1 or max_windows < 2:
        raise AnalysisRankingError("ranking needs at least one slot and two windows")
    record = load_video_analysis_record(package_directory / VIDEO_ANALYSIS_RECORD_FILE_NAME)
    if not record.analysed:
        raise AnalysisRankingError("there is no judgement to rank")
    providers = {item.analysis.analysis_provider for item in record.analysed}
    if not providers <= BOUGHT_ANALYSIS_PROVIDERS:
        raise AnalysisRankingError("this judgement was not bought from a model")
    total = interest_weight + story_weight
    # Equal scores fall back to the record's order, which is the plan's --
    # ride order -- rather than the identifier's, which is a hash.
    scored = sorted(
        (
            (
                (
                    item.analysis.visual_interest_score * interest_weight
                    + item.analysis.story_relevance_score * story_weight
                )
                / total,
                index,
                item.event_id,
            )
            for index, item in enumerate(record.analysed)
        ),
        key=lambda triple: (-triple[0], triple[1]),
    )
    cut = scored[min(slots, len(scored)) - 1][0]
    around = [event_id for score, _, event_id in scored if score >= cut - band]
    return around[:max_windows]


def rank_windows(
    package_directory: Path,
    *,
    compare: Comparator,
    upload: Callable[[Path, str], str],
    band: float = DEFAULT_RANK_BAND,
    slots: int = DEFAULT_SLOTS,
    max_windows: int = DEFAULT_MAX_WINDOWS,
    group_size: int = DEFAULT_GROUP_SIZE,
    provider: str = "gemini",
    overwrite: bool = False,
    attempts: int = 2,
) -> Path:
    """Buy the model's order over the top windows and write it down.

    The copies already made for the judgement are what get sent; nothing is
    re-encoded. Groups are formed in score order, so every window in a
    group was scored alike and the comparison is between near-equals --
    which is the only comparison worth paying for. Ranks are global: the
    first group takes 1..n, the next n+1.., because a window in a lower
    band was already judged below every window in a higher one.

    A group whose comparison comes back with a hole is asked again, once;
    if it fails again that group is left unranked and the rest still count.
    On the real sixth day one incomplete answer out of four groups threw the
    whole ranking away; a ranking with one group missing is worth far more
    than none.
    """
    if not 2 <= group_size <= MAX_GROUP_SIZE:
        raise AnalysisRankingError("a group is between two and ten windows")
    destination = package_directory / WINDOW_RANKING_FILE_NAME
    if destination.exists() and not overwrite:
        raise FileExistsError("this package already carries a ranking; pass overwrite=True")

    ordered = windows_worth_ranking(
        package_directory, band=band, slots=slots, max_windows=max_windows
    )
    if len(ordered) < 2:
        raise AnalysisRankingError("fewer than two windows are close enough to be worth ranking")

    proxies = package_directory / PROXY_DIRECTORY_NAME
    ranks: dict[str, int] = {}
    next_rank = 1
    compared_groups = 0
    failed_groups = 0
    for start in range(0, len(ordered), group_size):
        group = ordered[start : start + group_size]
        if len(group) == 1:
            # A trailing single has nothing to be compared with; it ranks
            # last on its own.
            ranks[group[0]] = next_rank
            next_rank += 1
            continue
        pairs: list[tuple[str, str]] = []
        for event_id in group:
            proxy = proxies / f"{event_id}.mp4"
            if not proxy.is_file() or proxy.is_symlink():
                raise AnalysisRankingError("a window's copy is missing; run preflight first")
            pairs.append((event_id, upload(proxy, event_id)))
        order = _complete_order(compare, pairs, group, attempts=attempts)
        if order is None:
            # The model answered with a hole twice. That group stays unranked
            # -- the selection falls back to scores for it -- rather than the
            # whole ranking being thrown away over one bad answer.
            failed_groups += 1
            continue
        compared_groups += 1
        for event_id in order:
            ranks[event_id] = next_rank
            next_rank += 1
    if failed_groups and not compared_groups:
        raise AnalysisRankingError("the comparator returned an incomplete order for every group")

    return write_window_ranking(
        destination, WindowRanking(provider=provider, ranks=ranks), overwrite=True
    )


def _complete_order(
    compare: Comparator,
    pairs: list[tuple[str, str]],
    group: Sequence[str],
    *,
    attempts: int,
) -> list[str] | None:
    """The comparator's order over exactly this group, or None after `attempts` tries."""
    if attempts < 1:
        raise AnalysisRankingError("a comparison needs at least one attempt")
    for _ in range(attempts):
        try:
            order = list(compare(pairs))
        except Exception as error:  # noqa: BLE001 - the transport's own error class is not imported here
            if not _is_incomplete_answer(error):
                raise
            continue
        if sorted(order) == sorted(group):
            return order
    return None


def _is_incomplete_answer(error: Exception) -> bool:
    """A model answer with a hole in it, as the transport reports it; nothing else is swallowed."""
    text = str(error).lower()
    return "incomplete ranking" in text or "returned no ranking" in text


def ranks_for(package_directory: Path) -> Mapping[str, int] | None:
    """The bought ranking, or None when the package has none.

    A ranking that cannot be read is an error rather than a silent absence,
    for the same reason a judgement is: a film cut without it is a different
    film, and nobody would see it happen.
    """
    path = package_directory / WINDOW_RANKING_FILE_NAME
    if not path.exists():
        return None
    ranking = load_window_ranking(path)
    if ranking.provider not in BOUGHT_ANALYSIS_PROVIDERS:
        raise AnalysisRankingError("this ranking was not bought from a model")
    return ranking.ranks


def plan_ranking_cost(
    package_directory: Path,
    *,
    band: float = DEFAULT_RANK_BAND,
    slots: int = DEFAULT_SLOTS,
    max_windows: int = DEFAULT_MAX_WINDOWS,
    group_size: int = DEFAULT_GROUP_SIZE,
) -> dict[str, object]:
    """What a ranking would send and roughly cost. Sends nothing."""
    ordered = windows_worth_ranking(
        package_directory, band=band, slots=slots, max_windows=max_windows
    )
    groups = max(0, (len(ordered) + group_size - 1) // group_size)
    plan = plan_analysis_run(package_directory)
    seconds_each = plan.candidates[0].duration_s if plan.candidates else 12.0
    # Low-resolution video: about 100 tokens a second; a short ordered answer.
    input_tokens = int(len(ordered) * seconds_each * 100)
    output_tokens = groups * 60
    usd = input_tokens / 1e6 * 0.30 + output_tokens / 1e6 * 2.50
    return {
        "windows_to_rank": len(ordered),
        "groups": groups,
        "estimated_jpy": round(usd * 150.0, 2),
    }
