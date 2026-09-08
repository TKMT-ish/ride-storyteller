"""Hand one account a short-lived read of its own object, and nothing else.

`app.tenancy` decided which objects an account may reach, `app.retention`
decided how long they exist, and `app.tenant_migration` put the objects
that predate accounts inside those two rules. What is still missing is the
only way an account is ever supposed to see a stored proxy again: a URL.

A signed URL is a bearer capability. Whoever holds it is the account, for
as long as it lasts, with no further check -- so every question this module
answers has to be answered *before* the signature exists, not when the link
is used. Three rules follow, and like the three modules above they are
deliberately dull:

*The ownership check comes before the signature, not before the fetch.*
`require_own_object` is called first, on the way out, exactly as it is
before judging or ranking. A URI stored in a package, restored from a
backup or edited by hand is not evidence of who owns it, and a signature
laid over an unchecked name would turn that non-evidence into access.

*A link never outlives the object it points at.* Its life is the shorter of
its own ceiling and what remains of the object's retention period. A link
that resolves after the deletion deadline is a broken promise; one that
resolves to nothing afterwards is a promise kept as a bug report. Both are
avoided by asking `app.retention.deletion_deadline` at signing time. The
ceiling itself is minutes rather than days because a URL, once issued, is
copied into chat logs, browser history and screenshots, where the fact that
it is a capability is invisible.

*Reads only.* A signed URL that can write is a different promise, with a
different failure (somebody else's ride replaced rather than seen), so this
module takes no method argument at all rather than defaulting to one.

Refusals never repeat the object they refused, the same rule `app.tenancy`
sets: a refusal grants nothing, so there is nothing the name would be part
of, and the message travels into logs the account cannot be assumed to own.
A *granted* link necessarily carries the object name -- that is what a URL
is -- and hiding it from the returned value would be theatre.

There is no CLI. `migrate` and `sweep` needed one because a person has to
approve them; a link is issued to whatever is already asking on an
account's behalf, and a terminal command whose output is a working
capability is the copy-into-a-log hazard above, wearing a prompt.

Nothing here connects by import: the Google client is constructed inside
the call, or injected.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

from app.retention import (
    DEFAULT_RETENTION_DAYS,
    RetentionError,
    StoredObject,
    deletion_deadline,
)
from app.tenancy import TenancyError, require_own_object

# Long enough to open a clip and watch it, short enough that a link found
# later in a log has almost certainly stopped working. Google's V4 signing
# allows a week; a week is a password.
MAX_LINK_SECONDS = 900

# What a caller gets when it does not say. Five minutes covers a fetch and
# a re-fetch after a dropped connection.
DEFAULT_LINK_SECONDS = 300

# Below this a link is not worth issuing: by the time it reaches the caller
# it has expired, and an expired link reads as a broken feature rather than
# as an object nearing its deletion deadline.
_MINIMUM_LINK_SECONDS = 1


class SignedLinkError(RuntimeError):
    """Raised when a link cannot be issued for this object, or at all."""


@dataclass(frozen=True)
class SignedLink:
    """One issued capability: where it points and when it stops working.

    `expires_at` is here so a caller can say "this stops working at" without
    parsing the URL, and so a test can hold the module to the retention
    promise without a Google client.
    """

    url: str
    expires_at: datetime
    lifetime_seconds: int

    def __post_init__(self) -> None:
        if not self.url.strip():
            raise SignedLinkError("a link that points nowhere is not a link")
        if self.expires_at.tzinfo is None or self.expires_at.utcoffset() is None:
            raise SignedLinkError("a link's expiry without a timezone cannot be trusted")
        if self.lifetime_seconds < _MINIMUM_LINK_SECONDS:
            raise SignedLinkError("a link has to last at least a second to be worth issuing")


def _validate_now(now: datetime) -> datetime:
    if now.tzinfo is None or now.utcoffset() is None:
        raise SignedLinkError("signing needs a timezone-aware time to measure a link against")
    return now.astimezone(UTC)


def _validate_requested(seconds: int) -> int:
    if isinstance(seconds, bool) or not isinstance(seconds, int):
        raise SignedLinkError("a link's life must be a whole number of seconds")
    if seconds < _MINIMUM_LINK_SECONDS:
        raise SignedLinkError("a link has to last at least a second to be worth issuing")
    if seconds > MAX_LINK_SECONDS:
        raise SignedLinkError(f"a link must not outlast {MAX_LINK_SECONDS} seconds")
    return seconds


def link_lifetime(
    *,
    now: datetime,
    uploaded_at: datetime,
    retention_days: int = DEFAULT_RETENTION_DAYS,
    requested_seconds: int = DEFAULT_LINK_SECONDS,
) -> int:
    """How many seconds this link may last: the shorter of the two limits.

    Clamping rather than refusing when the object is close to its deadline
    is the honest answer -- the object still exists, and a link for the time
    it has left is a real read of a real thing. Refusing only starts once
    there is no time left at all, because then the link would either point
    past the deletion promise or point at nothing.
    """
    moment = _validate_now(now)
    requested = _validate_requested(requested_seconds)
    try:
        deadline = deletion_deadline(uploaded_at, retention_days=retention_days)
    except RetentionError as error:
        raise SignedLinkError(f"that object cannot be aged, so it cannot be signed: {error}") from (
            error
        )
    remaining = (deadline - moment).total_seconds()
    if remaining < _MINIMUM_LINK_SECONDS:
        raise SignedLinkError("that object has reached its deletion deadline and is not linkable")
    return min(requested, int(remaining))


def _checked_name(uri: str, *, account_id: str) -> str:
    try:
        return require_own_object(uri, account_id=account_id)
    except TenancyError as error:
        raise SignedLinkError("that object does not belong to this account") from error


def sign_object(
    bucket_name: str,
    stored: StoredObject,
    *,
    account_id: str,
    now: datetime,
    retention_days: int = DEFAULT_RETENTION_DAYS,
    lifetime_seconds: int = DEFAULT_LINK_SECONDS,
    client: object | None = None,
) -> SignedLink:
    """Issue a read of one object, after checking it is this account's.

    The object arrives as a `StoredObject` rather than a bare name because
    the upload time is not optional here: without it the retention limit
    cannot be applied, and a signer that silently skips that limit when the
    time is missing is the failure this module exists to prevent.
    """
    bucket = bucket_name.strip()
    if not bucket:
        raise SignedLinkError("signing needs a bucket to point into")
    name = _checked_name(stored.name, account_id=account_id)
    seconds = link_lifetime(
        now=now,
        uploaded_at=stored.uploaded_at,
        retention_days=retention_days,
        requested_seconds=lifetime_seconds,
    )
    storage = client
    if storage is None:
        from google.cloud import storage as google_storage

        storage = google_storage.Client()
    try:
        url = (
            storage.bucket(bucket)
            .blob(name)
            .generate_signed_url(
                version="v4",
                expiration=timedelta(seconds=seconds),
                method="GET",
            )
        )
    except SignedLinkError:
        raise
    except Exception as error:  # noqa: BLE001 - the cause is reported, the object is not
        raise SignedLinkError(f"that object could not be signed: {type(error).__name__}") from error
    if not isinstance(url, str) or not url.strip():
        raise SignedLinkError("the signer returned no link for that object")
    return SignedLink(
        url=url,
        expires_at=_validate_now(now) + timedelta(seconds=seconds),
        lifetime_seconds=seconds,
    )


def sign_objects(
    bucket_name: str,
    stored: tuple[StoredObject, ...] | list[StoredObject],
    *,
    account_id: str,
    now: datetime,
    retention_days: int = DEFAULT_RETENTION_DAYS,
    lifetime_seconds: int = DEFAULT_LINK_SECONDS,
    client: object | None = None,
) -> tuple[SignedLink, ...]:
    """Issue reads for several objects, or none of them.

    Every name is checked against the account before the first signature is
    produced. Checking as it goes would let a caller that asked for one
    window of somebody else's ride among fifty of its own walk away with
    the fifty and a refusal, which reads as a partial success rather than
    as the attempt it was.
    """
    for item in stored:
        _checked_name(item.name, account_id=account_id)
    return tuple(
        sign_object(
            bucket_name,
            item,
            account_id=account_id,
            now=now,
            retention_days=retention_days,
            lifetime_seconds=lifetime_seconds,
            client=client,
        )
        for item in stored
    )
