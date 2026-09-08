"""Run the judging steps from a terminal, with the spending step held back.

The planning, preparing and judging of a ride's footage existed only as
library calls, so the runbook had steps nobody could type. That mattered
most for the one step that costs money: the figures a person is asked to
approve should come from a command they ran themselves, not from a number
quoted at them.

Three subcommands, and the split between them is the point.

- `plan` reads the package and prints what judging would send and cost. It
  opens no video and touches no network.
- `preflight` makes every clip a run would send, locally, and reports what
  they actually weigh. Still nothing leaves the machine.
- `screen` reads the GPS track and says how many windows the ride stood
  still in, and what skipping them would save. It drops nothing; see
  `app.analysis_screening` for why.
- `judge` is the one that spends. It uploads and calls Gemini, and it
  refuses to start unless `--i-approve-spending` is given along with the
  bucket to upload to. Approving a spend is a decision, so it is a thing
  somebody types, not a default.
- `tournament` is the cheaper alternative to `judge` + `rank` (Gate 7.2):
  it never buys a per-window verdict, only comparisons, and orders every
  candidate rather than only the ones a judgement left near the cut. See
  `app.analysis_tournament` for the shape and the cost this trades for.
- `compare` reads what both paths already bought -- a judgement+ranking and
  a tournament ranking -- and says what each would keep and cost. It buys
  nothing new; see `app.analysis_compare`.
- `stride-preview` filters a package's bought judgement down to the
  windows a coarser stride (Gate 7.3) would have produced, and says what
  the film would keep. It buys nothing new; see `app.analysis_stride_preview`.
- `retention` is the only subcommand that destroys anything. It reads the
  bucket, not a package -- an object no package remembers is exactly the
  one that must not be left behind -- and it refuses to delete unless
  `--i-approve-deletion` is typed, the same wall `judge` puts in front of
  spending. See `app.retention`.
- `migrate` adopts the objects that predate accounts: it puts an account's
  prefix in front of every untenanted name so a sweep and a forget can
  reach them at all. It reads the whole bucket, not a package, and refuses
  to move anything unless `--i-approve-migration` is typed. See
  `app.tenant_migration`.

Google is imported only inside `judge`, `rank` and `tournament`, after
their approval flag has been checked. `plan` and `preflight` run on a
machine with no cloud libraries at all.
"""

from __future__ import annotations

import argparse
import json
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import UTC, datetime
from pathlib import Path

from app.analysis_compare import AnalysisCompareError, compare_selection_paths
from app.analysis_preflight import run_preflight
from app.analysis_ranking import (
    RANKING_PROMPT,
    AnalysisRankingError,
    plan_ranking_cost,
    rank_windows,
)
from app.analysis_record import VIDEO_ANALYSIS_RECORD_FILE_NAME, load_video_analysis_record
from app.analysis_run import (
    DEFAULT_BUDGET_JPY,
    PARTIAL_RECORD_FILE_NAME,
    AnalysisRunError,
    AnalysisRunPlan,
    judgements_already_bought,
    plan_analysis_run,
    run_analysis,
    write_analysis_settings,
)
from app.analysis_screening import (
    DEFAULT_STILL_SPEED_MPS,
    AnalysisScreeningError,
    screening_report,
)
from app.analysis_stride_preview import AnalysisStridePreviewError, preview_stride_selection
from app.analysis_tournament import (
    AnalysisTournamentError,
    plan_tournament_cost,
    run_tournament,
)
from app.retention import (
    DEFAULT_RETENTION_DAYS,
    RetentionError,
    forget_account,
    sweep,
)
from app.tenant_migration import MigrationError, migrate_account


class AnalysisCommandError(RuntimeError):
    """Raised when a command cannot do what was asked of it."""


class CloudSignInExpired(AnalysisCommandError):
    """Raised when Google will not accept this machine's sign-in.

    A sign-in that has run out looks, from the outside, like any other
    failure: the console said only that the job failed, and the terminal
    printed a stack of somebody else's frames. Both readings are wrong in
    the same expensive way -- the run did not fail because of the ride, the
    package or the budget, and there is exactly one thing to do about it.
    So it is told apart from a package that refused the request, and the
    thing to do is in the message.
    """


# The names Google's libraries give this. They are matched by name because
# importing them here would defeat the rule the module is built around:
# nothing reachable by importing this file can talk to Google.
_SIGN_IN_FAILURES = frozenset({"DefaultCredentialsError", "RefreshError", "Unauthenticated"})


def _is_sign_in_failure(error: BaseException) -> bool:
    """Whether this failure, or something under it, is a refused sign-in."""
    seen: set[int] = set()
    current: BaseException | None = error
    while current is not None and id(current) not in seen:
        seen.add(id(current))
        kind = type(current)
        if kind.__module__.startswith("google.") and kind.__name__ in _SIGN_IN_FAILURES:
            return True
        current = current.__cause__ or current.__context__
    return False


@contextmanager
def _sign_in_understood() -> Iterator[None]:
    """Turn a refused sign-in into an answer, and leave everything else alone."""
    try:
        yield
    except Exception as error:
        if not _is_sign_in_failure(error):
            raise
        raise CloudSignInExpired(
            "Google will not accept this machine's sign-in; run "
            "`gcloud auth application-default login` and try again. "
            "Whatever was already bought is kept and is not bought twice."
        ) from error


def _plan(package: Path, *, budget_jpy: float) -> AnalysisRunPlan:
    try:
        return plan_analysis_run(package, budget_jpy=budget_jpy)
    except AnalysisRunError as error:
        raise AnalysisCommandError(str(error)) from error


def command_plan(
    package: Path, *, budget_jpy: float, stride_s: float | None = None
) -> dict[str, object]:
    """What judging this ride would send and cost. Sends nothing.

    With `stride_s` the stride is fixed into the package first, so every later
    step plans the same windows.
    """
    if stride_s is not None:
        try:
            write_analysis_settings(package, stride_s=stride_s)
        except AnalysisRunError as error:
            raise AnalysisCommandError(str(error)) from error
    return _plan(package, budget_jpy=budget_jpy).to_dict()


def command_preflight(package: Path, *, budget_jpy: float, rebuild: bool) -> dict[str, object]:
    """Make every clip a run would send, and weigh them. Sends nothing."""
    plan = _plan(package, budget_jpy=budget_jpy)
    result = run_preflight(package, plan, rebuild=rebuild)
    return {"plan": plan.to_dict(), "preflight": result.to_dict()}


def command_screen(package: Path, *, speed_mps: float) -> dict[str, object]:
    """How much of this ride stood still, and what skipping it would save."""
    try:
        return screening_report(package, speed_mps=speed_mps)
    except AnalysisScreeningError as error:
        raise AnalysisCommandError(str(error)) from error


def command_judge(
    package: Path,
    *,
    budget_jpy: float,
    bucket: str,
    prefix: str,
    approved: bool,
    overwrite: bool,
    refresh_top: int = 0,
    account_id: str | None = None,
) -> dict[str, object]:
    """Upload and judge. This is the step that spends money.

    `refresh_top` buys the judgement again for the record's best-scored
    windows, so that questions added to the model since -- the photogenic
    score -- are answered where it matters (the owner, 2026-09-07: the top
    forty of each day).

    The approval flag is checked before anything is imported that could
    reach Google, so a mistyped command cannot begin an upload.
    """
    if not approved:
        raise AnalysisCommandError(
            "judging uploads footage and bills for it; "
            "run `plan` first, then pass --i-approve-spending to go ahead"
        )
    if not bucket.strip():
        raise AnalysisCommandError("judging needs --bucket to upload to")

    from app.analysis_adapters import judge_with, upload_to_bucket
    from app.video import GeminiVideoAnalyzer, VertexAIGeminiVideoTransport

    plan = _plan(package, budget_jpy=budget_jpy)
    carried = judgements_already_bought(package / PARTIAL_RECORD_FILE_NAME)
    # A rerun that adds windows to a judged package (a moment the stride
    # missed) carries the finished record too and buys only the rest.
    finished = package / VIDEO_ANALYSIS_RECORD_FILE_NAME
    kept_from_record: set[str] = set()
    if overwrite and finished.exists():
        kept_from_record = {item.event_id for item in load_video_analysis_record(finished).analysed}
    planned = {candidate.event_id for candidate in plan.candidates}
    refresh: set[str] = set()
    if refresh_top > 0 and overwrite and finished.exists():
        held = load_video_analysis_record(finished).analysed
        by_score = sorted(
            held,
            key=lambda item: (
                -(
                    0.4 * item.analysis.visual_interest_score
                    + 0.6 * item.analysis.story_relevance_score
                )
            ),
        )
        refresh = {
            item.event_id
            for item in by_score[:refresh_top]
            if item.event_id in planned and item.analysis.photogenic_score is None
        }
    already = ((set(carried) | kept_from_record) - refresh) & planned
    with _sign_in_understood():
        analyzer = GeminiVideoAnalyzer(VertexAIGeminiVideoTransport.from_environment())
        record = run_analysis(
            package,
            plan,
            upload=upload_to_bucket(bucket, prefix=prefix, account_id=account_id),
            analyse=judge_with(analyzer, account_id=account_id),
            overwrite=overwrite,
            refresh=refresh,
        )
    return {
        "plan": plan.to_dict(),
        "record_written": record.name,
        # An earlier attempt that broke part-way is not paid for twice, and
        # neither is a finished record a rerun only adds to.
        "carried_from_earlier_attempt": len(carried),
        "carried_from_finished_record": len((kept_from_record - refresh) & planned),
        "refreshed": len(refresh),
        "newly_bought": len(planned - already),
    }


def command_rank(
    package: Path,
    *,
    bucket: str,
    prefix: str,
    approved: bool,
    overwrite: bool,
    account_id: str | None = None,
) -> dict[str, object]:
    """Buy the model's order over the near-equal windows. This spends, a little.

    Same gate as judging: nothing is imported that could reach Google until
    the approval flag has been checked.
    """
    if not approved:
        raise AnalysisCommandError(
            "ranking bills for the comparison; pass --i-approve-spending to go ahead"
        )
    if not bucket.strip():
        raise AnalysisCommandError("ranking needs --bucket the copies were judged from")

    from app.analysis_adapters import rank_with, upload_to_bucket
    from app.video import VertexAIGeminiVideoTransport

    with _sign_in_understood():
        transport = VertexAIGeminiVideoTransport.from_environment()
    uploader = upload_to_bucket(bucket, prefix=prefix, account_id=account_id)
    candidates = {c.event_id: c for c in plan_analysis_run(package).candidates}

    def upload(proxy: Path, event_id: str) -> str:
        candidate = candidates.get(event_id)
        if candidate is None:
            raise AnalysisCommandError("a ranked window is not in this package's plan")
        # The copies are already in the bucket from judging; putting the same
        # object under the same name again is idempotent and cheap.
        return uploader(proxy, candidate)

    try:
        cost = plan_ranking_cost(package)
        with _sign_in_understood():
            written = rank_windows(
                package,
                compare=rank_with(transport, prompt=RANKING_PROMPT, account_id=account_id),
                upload=upload,
                overwrite=overwrite,
            )
    except AnalysisRankingError as error:
        raise AnalysisCommandError(str(error)) from error
    return {"ranking_written": written.name, "cost": cost}


def command_compare(package: Path) -> dict[str, object]:
    """What the judged+ranked path keeps against what its tournament ranking would.

    Sends nothing.
    """
    try:
        return compare_selection_paths(package)
    except AnalysisCompareError as error:
        raise AnalysisCommandError(str(error)) from error


def command_stride_preview(package: Path, *, stride_s: float) -> dict[str, object]:
    """What a coarser stride would keep of a package's bought selection.

    Sends nothing; filters the already-judged, already-ranked candidates
    down to the ones a coarser stride would have produced (Gate 7.3).
    """
    try:
        return preview_stride_selection(package, stride_s=stride_s).to_dict()
    except AnalysisStridePreviewError as error:
        raise AnalysisCommandError(str(error)) from error


def command_tournament(
    package: Path,
    *,
    bucket: str,
    prefix: str,
    approved: bool,
    overwrite: bool,
    account_id: str | None = None,
) -> dict[str, object]:
    """Buy a full order over every candidate, without judging any of them first.

    Same gate as judging and ranking: nothing is imported that could reach
    Google until the approval flag has been checked. Unlike `rank`, this
    does not read a `VideoAnalysisRecord` -- it needs no judgement to have
    been bought, only the copies preflight already made.
    """
    if not approved:
        raise AnalysisCommandError(
            "a tournament bills for every comparison; pass --i-approve-spending to go ahead"
        )
    if not bucket.strip():
        raise AnalysisCommandError("a tournament needs --bucket to upload the copies to")

    from app.analysis_adapters import rank_with, upload_to_bucket
    from app.video import VertexAIGeminiVideoTransport

    with _sign_in_understood():
        transport = VertexAIGeminiVideoTransport.from_environment()
    uploader = upload_to_bucket(bucket, prefix=prefix, account_id=account_id)
    candidates = {c.event_id: c for c in plan_analysis_run(package).candidates}

    def upload(proxy: Path, event_id: str) -> str:
        candidate = candidates.get(event_id)
        if candidate is None:
            raise AnalysisCommandError("a ranked window is not in this package's plan")
        return uploader(proxy, candidate)

    try:
        cost = plan_tournament_cost(package)
        with _sign_in_understood():
            written = run_tournament(
                package,
                compare=rank_with(transport, prompt=RANKING_PROMPT, account_id=account_id),
                upload=upload,
                overwrite=overwrite,
            )
    except AnalysisTournamentError as error:
        raise AnalysisCommandError(str(error)) from error
    return {"tournament_ranking_written": written.name, "cost": cost}


# An account owns a prefix in the bucket; see `app.tenancy`. Without one
# the single-rider path is unchanged.
def command_retention(
    *,
    bucket: str,
    account_id: str,
    prefix: str,
    retention_days: int,
    forget: bool,
    approved: bool,
) -> dict[str, object]:
    """Say what one account's expiry would remove, and remove it if approved.

    No package argument, on purpose: what has to be deleted is what is in
    the bucket, and a package is a record of what somebody meant to upload,
    not of what is there.

    The payload carries counts, never names. A sweep is the natural thing
    to log, and a log of object names would undo the naming rule
    `app.analysis_adapters.object_name_for` and `app.tenancy` both keep.
    """
    if not account_id.strip():
        raise AnalysisCommandError("a sweep needs the account whose objects it may touch")
    if not bucket.strip():
        raise AnalysisCommandError("a sweep needs a bucket to look in")
    try:
        if forget:
            plan = forget_account(bucket, account_id=account_id, approved=approved)
        else:
            plan = sweep(
                bucket,
                account_id=account_id,
                now=datetime.now(UTC),
                retention_days=retention_days,
                prefix=prefix,
                approved=approved,
            )
    except RetentionError as error:
        raise AnalysisCommandError(str(error)) from error
    payload = plan.summary()
    payload["forget"] = forget
    payload["deleted"] = len(plan.due) if approved else 0
    if not approved and plan.due:
        payload["note"] = "nothing was deleted; pass --i-approve-deletion to go ahead"
    return payload


def command_migrate(*, bucket: str, account_id: str, approved: bool) -> dict[str, object]:
    """Adopt the objects that predate accounts into one account's prefix.

    No package argument and no prefix flag, both on purpose: what has to be
    adopted is whatever is in the bucket without an account in front of it,
    and narrowing that to a run would leave behind exactly the objects no
    run remembers.

    The payload carries counts, never names, the same rule
    `command_retention` keeps.
    """
    if not account_id.strip():
        raise AnalysisCommandError("a migration needs the account that will own the objects")
    if not bucket.strip():
        raise AnalysisCommandError("a migration needs a bucket to look in")
    try:
        plan = migrate_account(bucket, account_id=account_id, approved=approved)
    except MigrationError as error:
        raise AnalysisCommandError(str(error)) from error
    payload = plan.summary()
    payload["moved"] = len(plan.moves) if approved else 0
    if not approved and plan.moves:
        payload["note"] = "nothing was moved; pass --i-approve-migration to go ahead"
    return payload


_ACCOUNT_HELP = (
    "the account these objects belong to; uploads go under its own prefix, "
    "and nothing outside it is sent"
)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="python -m app.analysis_cli",
        description=(
            "Plan, prepare and judge one ride's footage. Planning and "
            "preparing send nothing; judging spends money and must be "
            "approved on the command line."
        ),
    )
    subcommands = parser.add_subparsers(dest="command", required=True)

    def with_common(name: str, help_text: str) -> argparse.ArgumentParser:
        sub = subcommands.add_parser(name, help=help_text)
        sub.add_argument("package", type=Path, help="the ride's package directory")
        sub.add_argument(
            "--budget-jpy",
            type=float,
            default=DEFAULT_BUDGET_JPY,
            help="the ceiling the cascade must fit inside (default: %(default)s)",
        )
        return sub

    plan_parser = with_common("plan", "say what judging would send and cost; sends nothing")
    plan_parser.add_argument(
        "--stride-s",
        type=float,
        default=None,
        dest="stride_s",
        help=(
            "fix this package's window stride in seconds (default 30); written into the "
            "package so preflight, judge and rank use the same windows"
        ),
    )

    preflight = with_common("preflight", "make and weigh every clip locally; sends nothing")
    preflight.add_argument(
        "--rebuild",
        action="store_true",
        help="re-encode clips that already exist rather than measuring them",
    )

    screen = with_common("screen", "count the windows the ride stood still in; sends nothing")
    screen.add_argument(
        "--still-speed-mps",
        type=float,
        default=DEFAULT_STILL_SPEED_MPS,
        dest="still_speed_mps",
        help="at or below this the ride counts as stopped (default: %(default)s)",
    )

    rank = with_common("rank", "have the model order the near-equal windows; spends a little")
    rank.add_argument("--bucket", default="", help="the GCS bucket the copies were judged from")
    rank.add_argument("--prefix", default="", help="the object-name prefix used when judging")
    rank.add_argument(
        "--account",
        default="",
        dest="account_id",
        help=_ACCOUNT_HELP,
    )
    rank.add_argument("--i-approve-spending", action="store_true", dest="approved")
    rank.add_argument("--overwrite", action="store_true")

    tournament = with_common(
        "tournament", "have the model order every window, no judgement bought; spends a little"
    )
    tournament.add_argument("--bucket", default="", help="the GCS bucket to upload copies to")
    tournament.add_argument("--prefix", default="", help="an object-name prefix within the bucket")
    tournament.add_argument(
        "--account",
        default="",
        dest="account_id",
        help=_ACCOUNT_HELP,
    )
    tournament.add_argument("--i-approve-spending", action="store_true", dest="approved")
    tournament.add_argument("--overwrite", action="store_true")

    compare = subcommands.add_parser(
        "compare",
        help="say what the judged+ranked path keeps against the tournament path; sends nothing",
    )
    compare.add_argument("package", type=Path, help="the ride's package directory")

    stride_preview = subcommands.add_parser(
        "stride-preview",
        help="say what a coarser stride would keep of a bought selection; sends nothing",
    )
    stride_preview.add_argument("package", type=Path, help="the ride's package directory")
    stride_preview.add_argument(
        "--stride-s",
        type=float,
        default=60.0,
        dest="stride_s",
        help="the coarser stride to preview, in seconds (default: %(default)s)",
    )

    retention = subcommands.add_parser(
        "retention",
        help="say what one account's expired uploads are, and delete them if approved",
    )
    retention.add_argument("--bucket", default="", help="the GCS bucket the copies live in")
    retention.add_argument(
        "--account",
        default="",
        dest="account_id",
        help="the account whose objects may be touched; nothing outside its prefix is",
    )
    retention.add_argument(
        "--prefix",
        default="",
        help="narrow the sweep to one run within the account; it can never widen it",
    )
    retention.add_argument(
        "--retention-days",
        type=int,
        default=DEFAULT_RETENTION_DAYS,
        dest="retention_days",
        help="how long an upload may be kept, in days (default: %(default)s)",
    )
    retention.add_argument(
        "--forget",
        action="store_true",
        help="delete everything this account has, whatever its age; ignores --prefix",
    )
    retention.add_argument(
        "--i-approve-deletion",
        action="store_true",
        dest="approved",
        help="required: without it the sweep lists and decides and stops",
    )

    migrate = subcommands.add_parser(
        "migrate",
        help="put an account's prefix in front of the objects that predate accounts",
    )
    migrate.add_argument("--bucket", default="", help="the GCS bucket the copies live in")
    migrate.add_argument(
        "--account",
        default="",
        dest="account_id",
        help="the account that will own every object without one; nothing else is touched",
    )
    migrate.add_argument(
        "--i-approve-migration",
        action="store_true",
        dest="approved",
        help="required: without it the migration lists and decides and stops",
    )

    judge = with_common("judge", "upload and judge; THIS SPENDS MONEY")
    judge.add_argument("--bucket", default="", help="the GCS bucket to upload clips to")
    judge.add_argument("--prefix", default="", help="an object-name prefix within the bucket")
    judge.add_argument(
        "--account",
        default="",
        dest="account_id",
        help=_ACCOUNT_HELP,
    )
    judge.add_argument(
        "--i-approve-spending",
        action="store_true",
        dest="approved",
        help="required: confirms the cost reported by `plan` is agreed to",
    )
    judge.add_argument(
        "--overwrite",
        action="store_true",
        help="buy a judgement again for a package that already carries one",
    )
    judge.add_argument(
        "--refresh-top",
        type=int,
        default=0,
        help=(
            "with --overwrite: buy the record's N best-scored windows again so the "
            "model's newer questions (the photogenic score) are answered for them"
        ),
    )
    return parser


def main(argv: list[str] | None = None) -> None:
    args = build_parser().parse_args(argv)
    try:
        if args.command == "plan":
            payload = command_plan(args.package, budget_jpy=args.budget_jpy, stride_s=args.stride_s)
        elif args.command == "preflight":
            payload = command_preflight(
                args.package, budget_jpy=args.budget_jpy, rebuild=args.rebuild
            )
        elif args.command == "screen":
            payload = command_screen(args.package, speed_mps=args.still_speed_mps)
        elif args.command == "rank":
            payload = command_rank(
                args.package,
                bucket=args.bucket,
                prefix=args.prefix,
                approved=args.approved,
                overwrite=args.overwrite,
                account_id=args.account_id or None,
            )
        elif args.command == "compare":
            payload = command_compare(args.package)
        elif args.command == "retention":
            payload = command_retention(
                bucket=args.bucket,
                account_id=args.account_id,
                prefix=args.prefix,
                retention_days=args.retention_days,
                forget=args.forget,
                approved=args.approved,
            )
        elif args.command == "migrate":
            payload = command_migrate(
                bucket=args.bucket,
                account_id=args.account_id,
                approved=args.approved,
            )
        elif args.command == "stride-preview":
            payload = command_stride_preview(args.package, stride_s=args.stride_s)
        elif args.command == "tournament":
            payload = command_tournament(
                args.package,
                bucket=args.bucket,
                prefix=args.prefix,
                approved=args.approved,
                overwrite=args.overwrite,
                account_id=args.account_id or None,
            )
        else:
            payload = command_judge(
                args.package,
                budget_jpy=args.budget_jpy,
                bucket=args.bucket,
                prefix=args.prefix,
                approved=args.approved,
                overwrite=args.overwrite,
                refresh_top=args.refresh_top,
                account_id=args.account_id or None,
            )
    except (AnalysisCommandError, AnalysisRunError) as error:
        raise SystemExit(str(error)) from error
    print(json.dumps(payload, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
