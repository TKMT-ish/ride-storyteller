"""An upload has to go away, completely, on time, and only its owner's."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta, timezone

import pytest

from app.retention import (
    DEFAULT_RETENTION_DAYS,
    MAX_RETENTION_DAYS,
    RetentionError,
    StoredObject,
    delete_objects,
    deletion_deadline,
    forget_account,
    is_due,
    list_account_objects,
    plan_forget,
    plan_sweep,
    sweep,
)
from app.tenancy import tenant_prefix

_ONE = "rider-one@example.com"
_TWO = "rider-two@example.com"
_BUCKET = "ride-proxies"
_NOW = datetime(2026, 9, 8, 12, 0, tzinfo=UTC)


def _name(account: str, stem: str, *, run: str = "") -> str:
    prefix = tenant_prefix(account)
    return f"{prefix}/{run}/{stem}.mp4" if run else f"{prefix}/{stem}.mp4"


def _stored(account: str, stem: str, *, age_days: float, run: str = "") -> StoredObject:
    return StoredObject(
        name=_name(account, stem, run=run),
        uploaded_at=_NOW - timedelta(days=age_days),
    )


@dataclass
class _Blob:
    name: str
    time_created: datetime | None
    deleted: list[str]

    def delete(self) -> None:
        self.deleted.append(self.name)


class _Bucket:
    def __init__(self, deleted: list[str]) -> None:
        self._deleted = deleted

    def blob(self, name: str) -> _Blob:
        return _Blob(name=name, time_created=None, deleted=self._deleted)


class _Client:
    """Enough of google.cloud.storage to list and delete, and to lie."""

    def __init__(self, blobs: list[_Blob] | None = None, *, honour_prefix: bool = True) -> None:
        self.deleted: list[str] = []
        self._blobs = blobs or []
        self._honour_prefix = honour_prefix
        self.listed_prefixes: list[str] = []

    def add(self, name: str, uploaded_at: datetime | None) -> None:
        self._blobs.append(_Blob(name=name, time_created=uploaded_at, deleted=self.deleted))

    def list_blobs(self, bucket: str, *, prefix: str = "") -> list[_Blob]:
        self.listed_prefixes.append(prefix)
        if not self._honour_prefix:
            return list(self._blobs)
        return [blob for blob in self._blobs if blob.name.startswith(prefix)]

    def bucket(self, name: str) -> _Bucket:
        return _Bucket(self.deleted)


# --- the deadline itself -------------------------------------------------


def test_a_deadline_is_the_upload_plus_the_period() -> None:
    uploaded = datetime(2026, 9, 1, tzinfo=UTC)
    assert deletion_deadline(uploaded, retention_days=7) == datetime(2026, 9, 8, tzinfo=UTC)


def test_an_upload_exactly_at_its_deadline_is_late_not_early() -> None:
    stored = _stored(_ONE, "a", age_days=DEFAULT_RETENTION_DAYS)
    assert is_due(stored, now=_NOW, retention_days=DEFAULT_RETENTION_DAYS)


def test_an_upload_a_moment_short_of_its_deadline_stays() -> None:
    stored = StoredObject(
        name=_name(_ONE, "a"),
        uploaded_at=_NOW - timedelta(days=DEFAULT_RETENTION_DAYS) + timedelta(seconds=1),
    )
    assert not is_due(stored, now=_NOW, retention_days=DEFAULT_RETENTION_DAYS)


def test_a_deadline_does_not_depend_on_which_clock_wrote_it() -> None:
    tokyo = timezone(timedelta(hours=9))
    same_moment = _NOW.astimezone(tokyo) - timedelta(days=DEFAULT_RETENTION_DAYS)
    stored = StoredObject(name=_name(_ONE, "a"), uploaded_at=same_moment)
    assert is_due(stored, now=_NOW, retention_days=DEFAULT_RETENTION_DAYS)


def test_an_upload_time_without_a_timezone_cannot_be_aged() -> None:
    with pytest.raises(RetentionError):
        StoredObject(name=_name(_ONE, "a"), uploaded_at=datetime(2026, 9, 1))


def test_a_sweep_needs_a_timezone_aware_now() -> None:
    with pytest.raises(RetentionError):
        is_due(_stored(_ONE, "a", age_days=99), now=datetime(2026, 9, 8))


def test_a_period_cannot_run_backwards_or_outlast_the_ceiling() -> None:
    with pytest.raises(RetentionError):
        deletion_deadline(_NOW, retention_days=-1)
    with pytest.raises(RetentionError):
        deletion_deadline(_NOW, retention_days=MAX_RETENTION_DAYS + 1)


def test_a_period_is_a_whole_number_of_days_not_a_flag() -> None:
    with pytest.raises(RetentionError):
        deletion_deadline(_NOW, retention_days=True)  # type: ignore[arg-type]
    with pytest.raises(RetentionError):
        deletion_deadline(_NOW, retention_days=1.5)  # type: ignore[arg-type]


# --- planning ------------------------------------------------------------


def test_a_plan_splits_the_expired_from_the_kept() -> None:
    plan = plan_sweep(
        [
            _stored(_ONE, "old", age_days=40),
            _stored(_ONE, "fresh", age_days=2),
            _stored(_ONE, "older", age_days=90),
        ],
        account_id=_ONE,
        now=_NOW,
    )
    assert len(plan.due) == 2
    assert plan.kept == 1
    assert plan.total == 3


def test_a_plans_summary_says_how_many_never_which() -> None:
    plan = plan_sweep([_stored(_ONE, "old", age_days=40)], account_id=_ONE, now=_NOW)
    rendered = repr(plan.summary())
    assert "old" not in rendered
    assert plan.summary()["due_for_deletion"] == 1
    assert plan.summary()["objects"] == 1


def test_another_accounts_object_stops_the_plan_rather_than_being_skipped() -> None:
    with pytest.raises(RetentionError):
        plan_sweep(
            [_stored(_ONE, "mine", age_days=40), _stored(_TWO, "theirs", age_days=40)],
            account_id=_ONE,
            now=_NOW,
        )


def test_a_refusal_does_not_repeat_the_object_it_refused() -> None:
    with pytest.raises(RetentionError) as raised:
        plan_sweep([_stored(_TWO, "theirs", age_days=40)], account_id=_ONE, now=_NOW)
    assert "theirs" not in str(raised.value)
    assert tenant_prefix(_TWO) not in str(raised.value)


def test_a_run_prefix_narrows_the_plan_and_an_answer_outside_it_stops_it() -> None:
    inside = _stored(_ONE, "a", age_days=40, run="run-1")
    outside = _stored(_ONE, "b", age_days=40, run="run-2")
    plan = plan_sweep([inside], account_id=_ONE, now=_NOW, prefix="run-1")
    assert len(plan.due) == 1
    with pytest.raises(RetentionError):
        plan_sweep([inside, outside], account_id=_ONE, now=_NOW, prefix="run-1")


def test_a_sibling_run_cannot_answer_for_the_run_it_shares_a_stem_with() -> None:
    ten = _stored(_ONE, "a", age_days=40, run="run-10")
    with pytest.raises(RetentionError):
        plan_sweep([ten], account_id=_ONE, now=_NOW, prefix="run-1")


def test_the_account_prefix_itself_is_not_an_object_to_delete() -> None:
    bare = StoredObject(name=tenant_prefix(_ONE), uploaded_at=_NOW - timedelta(days=99))
    with pytest.raises(RetentionError):
        plan_sweep([bare], account_id=_ONE, now=_NOW)


# --- forget --------------------------------------------------------------


def test_forgetting_takes_everything_regardless_of_age() -> None:
    plan = plan_forget(
        [_stored(_ONE, "old", age_days=99), _stored(_ONE, "today", age_days=0)],
        account_id=_ONE,
    )
    assert len(plan.due) == 2
    assert plan.kept == 0


def test_an_upload_stamped_in_the_future_is_still_forgotten() -> None:
    ahead = StoredObject(name=_name(_ONE, "skewed"), uploaded_at=_NOW + timedelta(days=3))
    assert len(plan_forget([ahead], account_id=_ONE).due) == 1
    assert plan_sweep([ahead], account_id=_ONE, now=_NOW, retention_days=0).kept == 1


def test_forgetting_still_refuses_another_accounts_object() -> None:
    with pytest.raises(RetentionError):
        plan_forget([_stored(_TWO, "theirs", age_days=1)], account_id=_ONE)


# --- deleting ------------------------------------------------------------


def test_deletion_refuses_without_approval() -> None:
    client = _Client()
    with pytest.raises(RetentionError):
        delete_objects(_BUCKET, [_name(_ONE, "a")], account_id=_ONE, client=client)
    assert client.deleted == []


def test_deletion_removes_exactly_the_named_objects() -> None:
    client = _Client()
    deleted = delete_objects(
        _BUCKET,
        [_name(_ONE, "a"), _name(_ONE, "b")],
        account_id=_ONE,
        approved=True,
        client=client,
    )
    assert deleted == 2
    assert client.deleted == [_name(_ONE, "a"), _name(_ONE, "b")]


def test_one_foreign_name_deletes_nothing_at_all() -> None:
    client = _Client()
    with pytest.raises(RetentionError):
        delete_objects(
            _BUCKET,
            [_name(_ONE, "a"), _name(_TWO, "theirs")],
            account_id=_ONE,
            approved=True,
            client=client,
        )
    assert client.deleted == []


def test_a_name_that_climbs_is_refused_rather_than_resolved() -> None:
    client = _Client()
    climbing = f"{tenant_prefix(_ONE)}/../{tenant_prefix(_TWO)}/theirs.mp4"
    with pytest.raises(RetentionError):
        delete_objects(_BUCKET, [climbing], account_id=_ONE, approved=True, client=client)
    assert client.deleted == []


# --- listing and the whole sweep ----------------------------------------


def test_a_listing_asks_only_for_the_accounts_own_prefix() -> None:
    client = _Client()
    client.add(_name(_ONE, "a"), _NOW)
    listed = list_account_objects(_BUCKET, account_id=_ONE, client=client)
    assert client.listed_prefixes == [f"{tenant_prefix(_ONE)}/"]
    assert [item.name for item in listed] == [_name(_ONE, "a")]


def test_an_object_without_an_upload_time_cannot_be_aged() -> None:
    client = _Client()
    client.add(_name(_ONE, "a"), None)
    with pytest.raises(RetentionError):
        list_account_objects(_BUCKET, account_id=_ONE, client=client)


def test_a_client_that_ignores_the_prefix_stops_the_sweep() -> None:
    client = _Client(honour_prefix=False)
    client.add(_name(_ONE, "mine"), _NOW - timedelta(days=99))
    client.add(_name(_TWO, "theirs"), _NOW - timedelta(days=99))
    with pytest.raises(RetentionError):
        sweep(_BUCKET, account_id=_ONE, now=_NOW, approved=True, client=client)
    assert client.deleted == []


def test_an_unapproved_sweep_lists_and_decides_and_stops() -> None:
    client = _Client()
    client.add(_name(_ONE, "old"), _NOW - timedelta(days=99))
    plan = sweep(_BUCKET, account_id=_ONE, now=_NOW, client=client)
    assert len(plan.due) == 1
    assert client.deleted == []


def test_an_approved_sweep_deletes_only_what_expired() -> None:
    client = _Client()
    client.add(_name(_ONE, "old"), _NOW - timedelta(days=99))
    client.add(_name(_ONE, "fresh"), _NOW - timedelta(days=1))
    plan = sweep(_BUCKET, account_id=_ONE, now=_NOW, approved=True, client=client)
    assert plan.kept == 1
    assert client.deleted == [_name(_ONE, "old")]


def test_an_orphan_no_package_remembers_is_still_swept() -> None:
    """The reason the sweep reads the bucket and never a package."""
    client = _Client()
    client.add(f"{tenant_prefix(_ONE)}/run-abandoned/ghost.mp4", _NOW - timedelta(days=99))
    plan = sweep(_BUCKET, account_id=_ONE, now=_NOW, approved=True, client=client)
    assert len(plan.due) == 1
    assert len(client.deleted) == 1


def test_forgetting_an_account_removes_every_age_it_holds() -> None:
    client = _Client()
    client.add(_name(_ONE, "old"), _NOW - timedelta(days=99))
    client.add(_name(_ONE, "today"), datetime.now(UTC))
    client.add(_name(_TWO, "theirs"), _NOW - timedelta(days=99))
    plan = forget_account(_BUCKET, account_id=_ONE, approved=True, client=client)
    assert len(plan.due) == 2
    assert _name(_TWO, "theirs") not in client.deleted
    assert len(client.deleted) == 2


def test_forgetting_without_approval_deletes_nothing() -> None:
    client = _Client()
    client.add(_name(_ONE, "old"), _NOW - timedelta(days=99))
    plan = forget_account(_BUCKET, account_id=_ONE, client=client)
    assert len(plan.due) == 1
    assert client.deleted == []


def test_a_sweep_needs_a_bucket() -> None:
    with pytest.raises(RetentionError):
        list_account_objects("   ", account_id=_ONE, client=_Client())
