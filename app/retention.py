"""Say when an upload has outlived its reason to exist, and take it away.

An uploaded proxy is a 480p copy of a public road, and the people on that
road did not agree to anything. The rider did. That asymmetry is the whole
of the retention question: what is kept is not the customer's own data, it
is a stranger's face in the customer's data, and the only honest answer to
"how long do you keep it?" is a number small enough to say out loud
(`docs/cloud-architecture-ja.md` §5).

The proxy is also the least valuable thing in the pipeline. What the money
buys is a judgement -- a few hundred bytes of text about a window -- and
the judgement is what the film is cut from. Once it is written, the copy it
was read from has no further use. Keeping it is not caution; it is a
liability nobody is paying to hold.

Three rules, all deliberately dull:

*Deletion is scoped by prefix, never by a list of names.* A list comes from
a package file, and a package can be edited, partial, restored from a
backup, or simply lost -- and the objects no package remembers are exactly
the ones that must not be left behind. The account's prefix is the only
scope whose completeness does not depend on a file we might not have.
Nothing here reads a package.

*A name that comes back from a listing is checked again before it is
deleted.* We asked for one prefix; the answer arrived over a network from a
client we did not write. Asking is not proof. The check is free, and
`app.tenancy` already holds the rule -- deleting is the most destructive
thing this codebase does to a bucket, so it goes through the same gate as
sending, not a looser one.

*A listing that answers outside the prefix stops the sweep.* Not skipped,
not filtered: stopped. If we asked for one account's space and something
else came back, the thing on the other end is not what we think it is, and
that is not the moment to start deleting.

Refusals and summaries never repeat an object's name, the same rule
`app.tenancy` keeps: a message about "this object" carries the path into a
log, which is where the contained thing gets out.
"""

from __future__ import annotations

from collections.abc import Callable, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

from app.tenancy import TenancyError, object_path, owns_object, scoped_prefix

# Long enough that a ride judged on a bad week is still there to re-cut,
# short enough to state to a stranger who was filmed without being asked.
DEFAULT_RETENTION_DAYS = 30

# A period past this is not a policy, it is the absence of one. Anything
# that needs a year of somebody else's face has a different problem.
MAX_RETENTION_DAYS = 365


class RetentionError(RuntimeError):
    """Raised when a deletion is unsafe, unapproved, or out of scope."""


@dataclass(frozen=True)
class StoredObject:
    """One uploaded proxy as the bucket describes it: a name and an age.

    Nothing else is carried. The window it came from, the ride it belongs
    to and the recording it was cut out of are all things this module would
    only be able to leak.
    """

    name: str
    uploaded_at: datetime

    def __post_init__(self) -> None:
        if not self.name.strip():
            raise RetentionError("an object cannot be swept without being named")
        if self.uploaded_at.tzinfo is None or self.uploaded_at.utcoffset() is None:
            raise RetentionError("an upload time without a timezone cannot be aged")


@dataclass(frozen=True)
class SweepPlan:
    """What a sweep would delete, in numbers.

    `names` is what the deletion needs; `summary` is what a person or a log
    is allowed to see. The split is the point -- a plan is the natural thing
    to print, and printing it must say how many, never which.
    """

    prefix: str
    retention_days: int
    due: tuple[str, ...]
    kept: int

    @property
    def total(self) -> int:
        return len(self.due) + self.kept

    def summary(self) -> dict[str, object]:
        return {
            "prefix": self.prefix,
            "retention_days": self.retention_days,
            "objects": self.total,
            "due_for_deletion": len(self.due),
            "kept": self.kept,
        }


def _validate_retention_days(retention_days: int) -> int:
    if isinstance(retention_days, bool) or not isinstance(retention_days, int):
        raise RetentionError("a retention period must be a whole number of days")
    if retention_days < 0:
        raise RetentionError("a retention period cannot run backwards")
    if retention_days > MAX_RETENTION_DAYS:
        raise RetentionError(f"a retention period must not exceed {MAX_RETENTION_DAYS} days")
    return retention_days


def _validate_now(now: datetime) -> datetime:
    if now.tzinfo is None or now.utcoffset() is None:
        raise RetentionError("a sweep needs a timezone-aware time to age uploads against")
    return now.astimezone(UTC)


def deletion_deadline(
    uploaded_at: datetime,
    *,
    retention_days: int = DEFAULT_RETENTION_DAYS,
) -> datetime:
    """The moment this upload must be gone by.

    A promise about the latest possible deletion, not a promise to keep it
    that long: once the judgement is written the copy may go at any time,
    and usually should.
    """
    if uploaded_at.tzinfo is None or uploaded_at.utcoffset() is None:
        raise RetentionError("an upload time without a timezone cannot be aged")
    return uploaded_at.astimezone(UTC) + timedelta(days=_validate_retention_days(retention_days))


def is_due(
    stored: StoredObject,
    *,
    now: datetime,
    retention_days: int = DEFAULT_RETENTION_DAYS,
) -> bool:
    """Whether this object has reached its deadline.

    The comparison is inclusive: an object exactly at its deadline is late,
    not early. A boundary that keeps things is the wrong boundary here.
    """
    return _validate_now(now) >= deletion_deadline(
        stored.uploaded_at, retention_days=retention_days
    )


def plan_sweep(
    stored: Sequence[StoredObject],
    *,
    account_id: str,
    now: datetime,
    retention_days: int = DEFAULT_RETENTION_DAYS,
    prefix: str = "",
) -> SweepPlan:
    """Split one account's objects into what must go and what may stay.

    Every name is checked against the account before it is even considered
    for deletion, and one name from outside stops the plan rather than
    being dropped from it.
    """
    scope = scoped_prefix(account_id, prefix=prefix)
    days = _validate_retention_days(retention_days)
    moment = _validate_now(now)
    due: list[str] = []
    kept = 0
    for item, name in _verified_names(stored, account_id=account_id, scope=scope):
        if is_due(item, now=moment, retention_days=days):
            due.append(name)
        else:
            kept += 1
    return SweepPlan(prefix=scope, retention_days=days, due=tuple(due), kept=kept)


def plan_forget(
    stored: Sequence[StoredObject],
    *,
    account_id: str,
) -> SweepPlan:
    """Every one of this account's objects, due now, whatever its age says.

    Not `plan_sweep` with a period of zero. That would still ask whether
    each upload's deadline has passed, and an object stamped in the future
    -- a clock adrift on the machine that wrote it, which is exactly the
    kind of thing nobody notices -- would answer no and survive a request
    to erase everything. A deletion that silently keeps something is worse
    than one that fails, so this asks no question it could get wrong.
    """
    scope = scoped_prefix(account_id, prefix="")
    names = [name for _, name in _verified_names(stored, account_id=account_id, scope=scope)]
    return SweepPlan(prefix=scope, retention_days=0, due=tuple(names), kept=0)


def _verified_names(
    stored: Sequence[StoredObject],
    *,
    account_id: str,
    scope: str,
) -> list[tuple[StoredObject, str]]:
    """Each object with its bare name, once it has proved it belongs here."""
    verified: list[tuple[StoredObject, str]] = []
    for item in stored:
        if not owns_object(item.name, account_id=account_id):
            raise RetentionError("a listing answered with an object from another account")
        name = object_path(item.name)
        if not _within(name, scope):
            raise RetentionError("a listing answered outside the prefix it was asked for")
        verified.append((item, name))
    return verified


def _within(name: str, scope: str) -> bool:
    """Whether `name` lies under `scope`, compared segment by segment.

    Raw prefix matching would let `u/ab/run1` answer for `u/ab/run10`, and
    a run is not the run next to it any more than an account is.
    """
    scope_segments = scope.strip("/").split("/")
    segments = name.split("/")
    if len(segments) <= len(scope_segments):
        return False
    return segments[: len(scope_segments)] == scope_segments


def list_account_objects(
    bucket_name: str,
    *,
    account_id: str,
    prefix: str = "",
    client: object | None = None,
) -> tuple[StoredObject, ...]:
    """Everything the bucket holds for this account, oldest information first.

    Building a plan from the listing rather than from a package is what
    makes an orphan -- an object no package remembers -- reachable at all.
    The Google import stays inside the call, so nothing connects by import.
    """
    name = bucket_name.strip()
    if not name:
        raise RetentionError("a sweep needs a bucket to look in")
    scope = scoped_prefix(account_id, prefix=prefix)
    storage = client
    if storage is None:
        from google.cloud import storage as google_storage

        storage = google_storage.Client()
    listed = []
    for blob in storage.list_blobs(name, prefix=f"{scope}/"):
        uploaded_at = getattr(blob, "time_created", None)
        if uploaded_at is None:
            raise RetentionError("an object without an upload time cannot be aged")
        listed.append(StoredObject(name=blob.name, uploaded_at=uploaded_at))
    return tuple(listed)


def delete_objects(
    bucket_name: str,
    names: Sequence[str],
    *,
    account_id: str,
    approved: bool = False,
    client: object | None = None,
    on_deleted: Callable[[str], None] | None = None,
) -> int:
    """Delete these objects, refusing any that is not this account's.

    `approved` is a wall, not a formality: this is the one call in the
    codebase that destroys somebody's data, and it should be as hard to
    reach by accident as spending money is.

    A name that fails the check aborts the whole call. Deleting the rest
    and reporting the failure afterwards would leave a half-swept prefix
    that no one can tell apart from a finished one.
    """
    bucket = bucket_name.strip()
    if not bucket:
        raise RetentionError("a deletion needs a bucket to act on")
    if not approved:
        raise RetentionError("deletion destroys data; pass approved=True to go ahead")
    for name in names:
        if not owns_object(name, account_id=account_id):
            raise RetentionError("that object does not belong to this account")
    storage = client
    if storage is None:
        from google.cloud import storage as google_storage

        storage = google_storage.Client()
    target = storage.bucket(bucket)
    deleted = 0
    for name in names:
        try:
            object_name = object_path(name)
        except TenancyError as error:  # pragma: no cover - owns_object rejects these first
            raise RetentionError("an object could not be named for deletion") from error
        target.blob(object_name).delete()
        deleted += 1
        if on_deleted is not None:
            on_deleted(object_name)
    return deleted


def sweep(
    bucket_name: str,
    *,
    account_id: str,
    now: datetime,
    retention_days: int = DEFAULT_RETENTION_DAYS,
    prefix: str = "",
    approved: bool = False,
    client: object | None = None,
) -> SweepPlan:
    """Plan and, if approved, carry out one account's expiry.

    Unapproved this lists and decides and stops -- the plan is the useful
    half, and it costs nothing to look.
    """
    stored = list_account_objects(bucket_name, account_id=account_id, prefix=prefix, client=client)
    plan = plan_sweep(
        stored,
        account_id=account_id,
        now=now,
        retention_days=retention_days,
        prefix=prefix,
    )
    if approved and plan.due:
        delete_objects(
            bucket_name,
            plan.due,
            account_id=account_id,
            approved=True,
            client=client,
        )
    return plan


def forget_account(
    bucket_name: str,
    *,
    account_id: str,
    approved: bool = False,
    client: object | None = None,
) -> SweepPlan:
    """Delete everything this account has, regardless of age.

    The deletion a retention policy owes a person who asks for one. It is
    one operation over one prefix because that is the only form of the
    request that can be answered completely: "delete my data" cannot be
    served by walking a list of the rides we happen to still have files for.

    It runs the same ownership and scope checks a sweep runs; only the
    question "is this old enough?" is dropped, because for this request
    there is no age at which the answer changes.
    """
    stored = list_account_objects(bucket_name, account_id=account_id, prefix="", client=client)
    plan = plan_forget(stored, account_id=account_id)
    if approved and plan.due:
        delete_objects(
            bucket_name,
            plan.due,
            account_id=account_id,
            approved=True,
            client=client,
        )
    return plan
