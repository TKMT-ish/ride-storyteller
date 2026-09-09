"""A bucket-side backstop, checked without touching the bucket's real config."""

from __future__ import annotations

import pytest

from app.bucket_lifecycle import (
    BACKSTOP_PREFIX,
    LifecycleError,
    check_backstop,
    evaluate_bucket_backstop,
    expected_backstop_rule,
    read_bucket_lifecycle_rules,
)
from app.retention import MAX_RETENTION_DAYS


class _Bucket:
    def __init__(self, lifecycle_rules: list[dict[str, object]]) -> None:
        self.lifecycle_rules = lifecycle_rules


class _Client:
    """Enough of google.cloud.storage to answer `get_bucket`."""

    def __init__(self, lifecycle_rules: list[dict[str, object]]) -> None:
        self._bucket = _Bucket(lifecycle_rules)
        self.requested: list[str] = []

    def get_bucket(self, name: str) -> _Bucket:
        self.requested.append(name)
        return self._bucket


def _delete_rule(age: int, *, prefixes: list[str] | None = None) -> dict[str, object]:
    condition: dict[str, object] = {"age": age}
    if prefixes is not None:
        condition["matchesPrefix"] = prefixes
    return {"action": {"type": "Delete"}, "condition": condition}


# --- the expected rule itself --------------------------------------------


def test_the_expected_rule_uses_the_retention_ceiling_not_the_default() -> None:
    rule = expected_backstop_rule()
    assert rule["condition"]["age"] == MAX_RETENTION_DAYS
    assert rule["action"] == {"type": "Delete"}


def test_the_expected_rule_is_scoped_to_the_tenant_root() -> None:
    rule = expected_backstop_rule()
    assert rule["condition"]["matchesPrefix"] == [BACKSTOP_PREFIX]


def test_a_zero_or_negative_backstop_age_is_refused() -> None:
    with pytest.raises(LifecycleError):
        expected_backstop_rule(retention_days=0)
    with pytest.raises(LifecycleError):
        expected_backstop_rule(retention_days=-1)


# --- comparing what a bucket actually has ---------------------------------


def test_a_rule_at_the_ceiling_scoped_to_the_tenant_root_passes() -> None:
    check = check_backstop([_delete_rule(MAX_RETENTION_DAYS, prefixes=[BACKSTOP_PREFIX])])
    assert check.ok
    assert check.found_age_days == MAX_RETENTION_DAYS


def test_a_bucket_wide_rule_with_no_prefix_filter_also_covers_the_tenancy() -> None:
    check = check_backstop([_delete_rule(MAX_RETENTION_DAYS)])
    assert check.ok


def test_no_rules_at_all_fails() -> None:
    check = check_backstop([])
    assert not check.ok
    assert check.found_age_days is None
    assert "no delete rule" in check.reason


def test_a_rule_scoped_to_only_one_account_does_not_cover_the_tenancy() -> None:
    narrow = f"{BACKSTOP_PREFIX}deadbeef00000000000000000000000/"
    check = check_backstop([_delete_rule(MAX_RETENTION_DAYS, prefixes=[narrow])])
    assert not check.ok
    assert check.found_age_days is None


def test_a_looser_rule_than_the_ceiling_fails_and_says_so() -> None:
    check = check_backstop([_delete_rule(MAX_RETENTION_DAYS + 100, prefixes=[BACKSTOP_PREFIX])])
    assert not check.ok
    assert check.found_age_days == MAX_RETENTION_DAYS + 100
    assert "looser" in check.reason


def test_a_tighter_rule_than_the_ceiling_fails_and_says_so() -> None:
    check = check_backstop([_delete_rule(10, prefixes=[BACKSTOP_PREFIX])])
    assert not check.ok
    assert check.found_age_days == 10
    assert "tighter" in check.reason


def test_a_non_delete_rule_is_ignored() -> None:
    storage_class_rule = {
        "action": {"type": "SetStorageClass", "storageClass": "NEARLINE"},
        "condition": {"age": 30, "matchesPrefix": [BACKSTOP_PREFIX]},
    }
    check = check_backstop([storage_class_rule])
    assert not check.ok


def test_the_nearest_covering_age_is_reported_when_several_rules_exist() -> None:
    check = check_backstop(
        [
            _delete_rule(400, prefixes=[BACKSTOP_PREFIX]),
            _delete_rule(200, prefixes=[BACKSTOP_PREFIX]),
        ]
    )
    assert not check.ok
    assert check.found_age_days == 200


# --- reading a bucket, and doing both steps together ----------------------


def test_reading_an_empty_bucket_name_is_refused() -> None:
    with pytest.raises(LifecycleError):
        read_bucket_lifecycle_rules("   ")


def test_reading_asks_the_client_for_the_named_bucket() -> None:
    client = _Client([_delete_rule(MAX_RETENTION_DAYS, prefixes=[BACKSTOP_PREFIX])])
    rules = read_bucket_lifecycle_rules("ride-proxies", client=client)
    assert client.requested == ["ride-proxies"]
    expected = {
        "action": {"type": "Delete"},
        "condition": {"age": MAX_RETENTION_DAYS, "matchesPrefix": [BACKSTOP_PREFIX]},
    }
    assert rules == (expected,)


def test_a_bucket_with_no_lifecycle_rules_reads_as_empty() -> None:
    client = _Client([])
    assert read_bucket_lifecycle_rules("ride-proxies", client=client) == ()


def test_evaluate_reads_and_checks_in_one_call() -> None:
    client = _Client([_delete_rule(MAX_RETENTION_DAYS, prefixes=[BACKSTOP_PREFIX])])
    check = evaluate_bucket_backstop("ride-proxies", client=client)
    assert check.ok


def test_evaluate_reports_the_missing_rule_for_an_unconfigured_bucket() -> None:
    client = _Client([])
    check = evaluate_bucket_backstop("ride-proxies", client=client)
    assert not check.ok
    assert check.expected_age_days == MAX_RETENTION_DAYS
