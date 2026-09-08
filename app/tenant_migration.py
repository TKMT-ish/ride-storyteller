"""Move the objects that predate accounts into the account that owns them.

`app.tenancy` gave every account a prefix and `app.retention` gave every
account a way to be forgotten, and both measurements ended at the same
wall: the objects already in the bucket are named `<window hash>.mp4` with
nothing in front of them, so they belong to no account. Nothing reaches
them. A sweep cannot expire them, `forget_account` cannot erase them, and
`require_own_object` refuses to send them anywhere. A retention promise
that cannot reach the files it is about is not a promise, which is why
this is a precondition of multi-tenancy rather than a tidying job.

Four rules, and like the two modules above they are deliberately dull:

*The destination is derived from the source, never chosen.* An account's
prefix goes in front of the name the object already has. Two different
objects therefore cannot land on one name, and a caller cannot aim a move
at somebody else's space by describing it differently.

*Copy, confirm, then delete.* Interrupted after the copy this leaves a
duplicate; interrupted the other way round it would leave a hole where a
stranger's face used to be recoverable and now is not. A duplicate is a
bill. A hole is somebody's ride. The order follows from which of those we
are willing to explain.

*An object already inside account space is left exactly where it is.* A
bucket part-way through a migration is the normal state of a resumed one,
so this counts them and moves on rather than stopping. What does stop the
plan is an object sitting under the tenant root that belongs to no account
-- that is not a state this codebase can produce, and guessing which
account it meant is the one mistake that cannot be undone.

*A name that climbs is refused, not resolved.* Same rule, same reason as
`app.tenancy`: a name with `..` in it has already said what it is for.

Plans and refusals carry counts, never names, for the reason
`app.analysis_adapters.object_name_for` exists at all.
"""

from __future__ import annotations

import re
from collections.abc import Callable, Sequence
from dataclasses import dataclass

from app.tenancy import (
    TENANT_ROOT,
    TenancyError,
    object_path,
    owns_object,
    tenant_prefix,
)

# The shape `app.tenancy.tenant_prefix` produces: half a SHA-256, lowercase.
_DIGEST = re.compile(r"\A[0-9a-f]{32}\Z")


class MigrationError(RuntimeError):
    """Raised when an object cannot be moved into an account safely."""


@dataclass(frozen=True)
class ObjectMove:
    """One object's old name and the name it will have afterwards."""

    source: str
    destination: str


@dataclass(frozen=True)
class MigrationPlan:
    """What a migration would move, and what it would leave alone.

    `moves` is what the migration needs; `summary` is what a person or a
    log may see. The split is the same one `app.retention.SweepPlan` makes
    and for the same reason: a plan is the natural thing to print.
    """

    prefix: str
    moves: tuple[ObjectMove, ...]
    already_owned: int
    other_accounts: int

    @property
    def total(self) -> int:
        return len(self.moves) + self.already_owned + self.other_accounts

    def summary(self) -> dict[str, object]:
        return {
            "prefix": self.prefix,
            "objects": self.total,
            "to_move": len(self.moves),
            "already_owned": self.already_owned,
            "other_accounts": self.other_accounts,
        }


def destination_for(name: str, *, account_id: str) -> str:
    """Where this untenanted object belongs once the account owns it.

    The account's prefix in front of the name the object already has. It is
    a pure function of the two, so a second run of a half-finished
    migration computes the same answer as the first.
    """
    bare = _safe_name(name)
    if _tenant_segment(bare) is not None:
        raise MigrationError("an object already in account space is not moved again")
    return f"{tenant_prefix(account_id)}/{bare}"


def plan_migration(names: Sequence[str], *, account_id: str) -> MigrationPlan:
    """Sort a bucket's objects into the ones this account must adopt.

    Every name is checked before it is classified, and one name that climbs
    -- or one sitting under the tenant root with no account behind it --
    stops the plan instead of being quietly dropped from it.
    """
    prefix = tenant_prefix(account_id)
    moves: list[ObjectMove] = []
    already_owned = 0
    other_accounts = 0
    for name in names:
        bare = _safe_name(name)
        digest = _tenant_segment(bare)
        if digest is None:
            moves.append(ObjectMove(source=bare, destination=f"{prefix}/{bare}"))
        elif owns_object(bare, account_id=account_id):
            already_owned += 1
        else:
            other_accounts += 1
    return MigrationPlan(
        prefix=prefix,
        moves=tuple(moves),
        already_owned=already_owned,
        other_accounts=other_accounts,
    )


def _safe_name(name: str) -> str:
    """The object's bare name, or a refusal that does not repeat it."""
    try:
        bare = object_path(name)
    except TenancyError as error:
        raise MigrationError("an object cannot be migrated without being named") from error
    if "\\" in bare:
        raise MigrationError("an object name that is not a plain path is refused")
    segments = bare.split("/")
    if any(segment in ("", ".", "..") for segment in segments):
        raise MigrationError("an object name that is not a plain path is refused")
    return bare


def _tenant_segment(bare: str) -> str | None:
    """The account digest this name lives under, or `None` if it is legacy.

    A name under the tenant root that does not carry a whole digest and at
    least one segment beneath it is not legacy and not tenanted; it is a
    thing this codebase cannot have written, so it raises rather than
    getting a guess.
    """
    segments = bare.split("/")
    if segments[0] != TENANT_ROOT:
        return None
    if len(segments) < 3 or not _DIGEST.match(segments[1]):
        raise MigrationError("an object sits in account space without an account")
    return segments[1]


def list_bucket_objects(bucket_name: str, *, client: object | None = None) -> tuple[str, ...]:
    """Every object name in the bucket, tenanted or not.

    No prefix is asked for, on purpose: the objects that need adopting are
    precisely the ones no prefix would return. The Google import stays
    inside the call so nothing connects by import.
    """
    bucket = bucket_name.strip()
    if not bucket:
        raise MigrationError("a migration needs a bucket to look in")
    storage = client
    if storage is None:
        from google.cloud import storage as google_storage

        storage = google_storage.Client()
    return tuple(blob.name for blob in storage.list_blobs(bucket))


def move_objects(
    bucket_name: str,
    moves: Sequence[ObjectMove],
    *,
    account_id: str,
    approved: bool = False,
    client: object | None = None,
    on_moved: Callable[[ObjectMove], None] | None = None,
) -> int:
    """Copy each object under the account, confirm it, then delete the old.

    `approved` is the same wall `app.retention.delete_objects` puts up, and
    for the same reason: the last step of a move destroys a name somebody
    else's package may still point at.

    Every destination is checked against the account before the first byte
    is copied. Checking as we go would leave a prefix half adopted and no
    way to tell it from a finished one.
    """
    bucket = bucket_name.strip()
    if not bucket:
        raise MigrationError("a migration needs a bucket to act on")
    if not approved:
        raise MigrationError("migration deletes the old name; pass approved=True to go ahead")
    for move in moves:
        source = _safe_name(move.source)
        if _tenant_segment(source) is not None:
            raise MigrationError("an object already in account space is not moved again")
        if destination_for(source, account_id=account_id) != _safe_name(move.destination):
            raise MigrationError("a move names a destination this account did not derive")
        if not owns_object(move.destination, account_id=account_id):
            raise MigrationError("that destination does not belong to this account")
    storage = client
    if storage is None:
        from google.cloud import storage as google_storage

        storage = google_storage.Client()
    target = storage.bucket(bucket)
    moved = 0
    for move in moves:
        source_blob = target.blob(move.source)
        if not target.blob(move.destination).exists():
            target.copy_blob(source_blob, target, move.destination)
        if not target.blob(move.destination).exists():
            raise MigrationError("a copy did not arrive; the old object was left in place")
        source_blob.delete()
        moved += 1
        if on_moved is not None:
            on_moved(move)
    return moved


def migrate_account(
    bucket_name: str,
    *,
    account_id: str,
    approved: bool = False,
    client: object | None = None,
) -> MigrationPlan:
    """Adopt every untenanted object in the bucket, if approved.

    Unapproved this lists and decides and stops, the same halt `sweep`
    makes: the plan is the useful half and it costs nothing to look.
    """
    names = list_bucket_objects(bucket_name, client=client)
    plan = plan_migration(names, account_id=account_id)
    if approved and plan.moves:
        move_objects(
            bucket_name,
            plan.moves,
            account_id=account_id,
            approved=True,
            client=client,
        )
    return plan
