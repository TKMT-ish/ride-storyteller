"""A second door on the same lock, in case the first one jams.

`app.retention` deletes on schedule, but it only runs when something calls
it: a cron job that stops firing, a CLI nobody remembers to run, an account
whose `sweep` silently starts failing. None of those failures show up as an
error anywhere a person is watching -- they show up as somebody's face
staying in a bucket a year after the promise was to delete it in thirty
days. The bucket itself has a feature for exactly this shape of failure --
Object Lifecycle Management -- and it does not care whether this codebase
is still alive to ask it to.

This module does not configure that feature. Writing bucket configuration
from inside the analysis path would make the backstop only as reliable as
the thing it exists to back up. It generates the rule the constants in
`app.retention` already promise, and reads back what the bucket actually
has, so the two can be compared and a mismatch reported in plain language --
same shape as `app.analysis_compare`, which buys nothing new either.

One rule, deliberately dull: **the backstop's age is the retention
ceiling, not the account default.** `app.retention.DEFAULT_RETENTION_DAYS`
is a per-account setting an operator could reasonably want to change;
`MAX_RETENTION_DAYS` is the number no account can exceed
(`app.retention._validate_retention_days` enforces it on every sweep). A
bucket-side rule set to the default would delete objects out from under an
account that had lawfully asked to keep them longer; a bucket-side rule
looser than the ceiling would fail to back up the one promise that must
never be broken. The ceiling is the only value both accounts and the
bucket can agree on without either reading the other's settings.

The prefix is `app.tenancy.TENANT_ROOT` -- every account's objects live
under it, and nothing else does, so a rule scoped there is a backstop for
the whole tenancy, not a guess at which account needs it most.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass

from app.retention import MAX_RETENTION_DAYS
from app.tenancy import TENANT_ROOT

# Every account's objects live under this prefix (`app.tenancy.tenant_prefix`);
# nothing else does. A rule scoped here backstops the whole tenancy.
BACKSTOP_PREFIX = f"{TENANT_ROOT}/"


class LifecycleError(RuntimeError):
    """Raised when a bucket's lifecycle configuration cannot be read or checked."""


@dataclass(frozen=True)
class BackstopCheck:
    """Whether the bucket has a delete rule that matches the retention ceiling.

    Carries ages, never object names -- there are none to carry; a
    lifecycle rule is bucket-wide configuration, not a listing.
    """

    ok: bool
    expected_age_days: int
    found_age_days: int | None
    reason: str

    def summary(self) -> dict[str, object]:
        return {
            "ok": self.ok,
            "expected_age_days": self.expected_age_days,
            "found_age_days": self.found_age_days,
            "reason": self.reason,
        }


def _validate_retention_days(retention_days: int) -> int:
    if isinstance(retention_days, bool) or not isinstance(retention_days, int):
        raise LifecycleError("a backstop age must be a whole number of days")
    if retention_days <= 0:
        raise LifecycleError("a backstop age must be a positive number of days")
    return retention_days


def expected_backstop_rule(
    *,
    retention_days: int = MAX_RETENTION_DAYS,
    prefix: str = BACKSTOP_PREFIX,
) -> dict[str, object]:
    """The one rule a correctly configured bucket has for this tenancy.

    Shaped like the dicts `google.cloud.storage.Bucket.lifecycle_rules`
    already returns, so it can sit next to what the bucket answers without
    translation on either side.
    """
    days = _validate_retention_days(retention_days)
    return {
        "action": {"type": "Delete"},
        "condition": {"age": days, "matchesPrefix": [prefix]},
    }


def read_bucket_lifecycle_rules(
    bucket_name: str,
    *,
    client: object | None = None,
) -> tuple[dict[str, object], ...]:
    """The bucket's own lifecycle rules, exactly as it reports them.

    Reads bucket configuration, not the objects in it -- there is no
    account to scope this to and nothing here that could leak a rider's
    ride. The Google import stays inside the call, the same rule
    `app.retention.list_account_objects` keeps.
    """
    name = bucket_name.strip()
    if not name:
        raise LifecycleError("a backstop check needs a bucket to look at")
    storage = client
    if storage is None:
        from google.cloud import storage as google_storage

        storage = google_storage.Client()
    bucket = storage.get_bucket(name)
    rules = getattr(bucket, "lifecycle_rules", None) or ()
    return tuple(dict(rule) for rule in rules)


def _is_delete_rule(rule: dict[str, object]) -> bool:
    action = rule.get("action")
    return isinstance(action, dict) and action.get("type") == "Delete"


def _rule_age_days(rule: dict[str, object]) -> int | None:
    condition = rule.get("condition")
    if not isinstance(condition, dict):
        return None
    age = condition.get("age")
    return age if isinstance(age, int) and not isinstance(age, bool) else None


def _covers_prefix(rule: dict[str, object], prefix: str) -> bool:
    """Whether this rule's scope reaches every object under `prefix`.

    No `matchesPrefix` at all means the rule applies to the whole bucket,
    which covers the tenancy along with everything else. A `matchesPrefix`
    narrower than `prefix` (a sub-account's own run, say) protects only
    part of the tenancy and is not the backstop this is looking for.
    """
    condition = rule.get("condition")
    matches = condition.get("matchesPrefix") if isinstance(condition, dict) else None
    if not matches:
        return True
    return any(isinstance(m, str) and prefix.startswith(m) for m in matches)


def check_backstop(
    raw_rules: Sequence[dict[str, object]],
    *,
    retention_days: int = MAX_RETENTION_DAYS,
    prefix: str = BACKSTOP_PREFIX,
) -> BackstopCheck:
    """Compare a bucket's actual rules against the one it is supposed to have.

    Pure comparison, no network -- the rules are already in hand. Reused by
    `evaluate_bucket_backstop` and tested directly against rules the world
    never had to send.
    """
    expected = _validate_retention_days(retention_days)
    covering = [
        rule for rule in raw_rules if _is_delete_rule(rule) and _covers_prefix(rule, prefix)
    ]
    if not covering:
        return BackstopCheck(
            ok=False,
            expected_age_days=expected,
            found_age_days=None,
            reason="no delete rule covers this tenancy; a broken sweep would keep objects forever",
        )
    ages = {age for rule in covering if (age := _rule_age_days(rule)) is not None}
    if expected in ages:
        return BackstopCheck(
            ok=True,
            expected_age_days=expected,
            found_age_days=expected,
            reason="a delete rule at the retention ceiling covers this tenancy",
        )
    found = min(ages) if ages else None
    if found is not None and found > expected:
        reason = (
            "the bucket's backstop is looser than the retention ceiling; "
            "a broken sweep could outlive it"
        )
    elif found is not None:
        reason = (
            "the bucket's backstop is tighter than the retention ceiling; "
            "it could delete objects an account was owed"
        )
    else:
        reason = "a delete rule covers this tenancy but names no age"
    return BackstopCheck(ok=False, expected_age_days=expected, found_age_days=found, reason=reason)


def evaluate_bucket_backstop(
    bucket_name: str,
    *,
    retention_days: int = MAX_RETENTION_DAYS,
    prefix: str = BACKSTOP_PREFIX,
    client: object | None = None,
) -> BackstopCheck:
    """Read a bucket's lifecycle rules and check them in one call."""
    raw_rules = read_bucket_lifecycle_rules(bucket_name, client=client)
    return check_backstop(raw_rules, retention_days=retention_days, prefix=prefix)
