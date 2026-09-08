"""Keep one account's uploads out of every other account's reach.

Everything in the analysis path was built for one rider on one machine:
the bucket prefix is a free-text flag, empty by default, and every window
of every ride lands beside every other. That is safe while there is one
account and stops being safe the moment there are two, because the objects
are proxies of somebody's ride -- other people's faces, plates and homes
are in them, put there by a camera pointed at a public road.

Two rules hold the line, and they are deliberately dull:

*An account's objects live under its own prefix.* The prefix is derived
from the account, never chosen by it, so no caller can name its way into
another account's space. It is a digest rather than the account itself,
because an object name is the one part of an upload that is read by people,
written to logs, and kept in bucket listings long after the clip is gone --
the same reason a window is named after its own hash and not after the
recording it came from (`app.analysis_adapters.object_name_for`).

*Nothing outside that prefix is ever read or sent.* A stored URI is not
evidence of who owns it. Checking on the way out costs nothing and is the
only check that survives a package being copied, restored from a backup, or
handed over by someone who edited it.

Refusals never repeat the object they refused. A message about "this URI"
would carry the very path the rule exists to contain into a log or a
console the account cannot be assumed to own.
"""

from __future__ import annotations

import hashlib
import re

# One segment marks the space as account-owned, so a bucket listing shows
# what is tenanted without anyone having to know the naming scheme.
TENANT_ROOT = "u"

# Half a SHA-256 is far past collision for a user table and still short
# enough to read in a listing.
_DIGEST_LENGTH = 32

_SAFE_SEGMENT = re.compile(r"\A[a-z0-9][a-z0-9._-]{0,127}\Z")


class TenancyError(RuntimeError):
    """Raised when an object does not belong to the account asking for it."""


def tenant_prefix(account_id: str) -> str:
    """The object prefix that belongs to this account, and to no other.

    Derived, not supplied: the account can no more choose its prefix than a
    window can choose its name. The account id itself never appears in it,
    so a bucket listing says how many accounts there are and nothing else
    about them.
    """
    cleaned = account_id.strip()
    if not cleaned:
        raise TenancyError("an account has to be known before its objects can be named")
    digest = hashlib.sha256(cleaned.encode("utf-8")).hexdigest()[:_DIGEST_LENGTH]
    return f"{TENANT_ROOT}/{digest}"


def object_path(uri: str) -> str:
    """The object name inside a bucket, whether given as `gs://` or bare.

    A caller that stored a bare name and a caller that stored a URI are
    asking the same question, and the answer must not depend on which.
    """
    text = uri.strip()
    if not text:
        raise TenancyError("an object cannot be checked without being named")
    if text.startswith("gs://"):
        remainder = text[len("gs://") :]
        _, separator, name = remainder.partition("/")
        if not separator or not name:
            raise TenancyError("an object URI names a bucket but no object")
        return name
    return text.lstrip("/")


def owns_object(uri: str, *, account_id: str) -> bool:
    """Whether this object lies inside this account's prefix.

    The comparison is on whole path segments. A prefix match on raw text
    would let `u/abcd` claim `u/abcdef/...`, which is a different account.
    Traversal is refused outright rather than resolved, because a name that
    tries to climb has already told us what it is for.
    """
    name = object_path(uri)
    if "\\" in name:
        return False
    segments = name.split("/")
    if any(segment in ("", ".", "..") for segment in segments):
        return False
    expected = tenant_prefix(account_id).split("/")
    if len(segments) <= len(expected):
        return False
    return segments[: len(expected)] == expected


def require_own_object(uri: str, *, account_id: str) -> str:
    """Return the object name, or refuse it without naming it.

    Called on the way out -- before an object is sent to be judged, ranked
    or signed -- so that a URI arriving from a stored package, a restored
    backup or an edited file cannot spend one account's money on another
    account's ride.
    """
    if not owns_object(uri, account_id=account_id):
        raise TenancyError("that object does not belong to this account")
    return object_path(uri)


def scoped_prefix(account_id: str, *, prefix: str = "") -> str:
    """Put a caller's own prefix underneath the account's, never beside it.

    The existing `--prefix` flag stays useful for telling one run from
    another; it just no longer decides which account's space is written to.
    """
    root = tenant_prefix(account_id)
    cleaned = prefix.strip("/")
    if not cleaned:
        return root
    for segment in cleaned.split("/"):
        if not _SAFE_SEGMENT.match(segment):
            raise TenancyError("a run's prefix must be plain path segments")
    return f"{root}/{cleaned}"
