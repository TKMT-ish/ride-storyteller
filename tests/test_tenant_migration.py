"""The objects that predate accounts have to become somebody's, safely."""

from __future__ import annotations

import pytest

from app.tenancy import TenancyError, tenant_prefix
from app.tenant_migration import (
    MigrationError,
    ObjectMove,
    destination_for,
    list_bucket_objects,
    migrate_account,
    move_objects,
    plan_migration,
)

_ONE = "rider-one@example.com"
_TWO = "rider-two@example.com"
_BUCKET = "ride-proxies"


class _Blob:
    def __init__(self, store: dict[str, str], name: str) -> None:
        self._store = store
        self.name = name

    def exists(self) -> bool:
        return self.name in self._store

    def delete(self) -> None:
        self._store.pop(self.name, None)


class _Bucket:
    """Enough of a GCS bucket to copy, confirm and delete."""

    def __init__(self, store: dict[str, str], *, copies_vanish: bool = False) -> None:
        self.store = store
        self.copied: list[tuple[str, str]] = []
        self._copies_vanish = copies_vanish

    def blob(self, name: str) -> _Blob:
        return _Blob(self.store, name)

    def copy_blob(self, source: _Blob, destination: "_Bucket", new_name: str) -> _Blob:
        self.copied.append((source.name, new_name))
        if not self._copies_vanish:
            destination.store[new_name] = self.store[source.name]
        return destination.blob(new_name)


class _Client:
    def __init__(self, names: dict[str, str] | None = None, **kwargs: bool) -> None:
        self.store: dict[str, str] = dict(names or {})
        self._bucket = _Bucket(self.store, **kwargs)
        self.listed: list[str] = []

    def list_blobs(self, bucket: str, *, prefix: str = "") -> list[_Blob]:
        self.listed.append(bucket)
        return [_Blob(self.store, name) for name in sorted(self.store)]

    def bucket(self, name: str) -> _Bucket:
        return self._bucket


def _legacy(*stems: str) -> dict[str, str]:
    return {f"{stem}.mp4": stem for stem in stems}


# --- where an object goes ------------------------------------------------


def test_the_destination_is_the_account_prefix_in_front_of_the_old_name() -> None:
    assert destination_for("abc123.mp4", account_id=_ONE) == f"{tenant_prefix(_ONE)}/abc123.mp4"


def test_a_run_prefix_inside_the_old_name_is_kept_underneath_the_account() -> None:
    moved = destination_for("run1/abc123.mp4", account_id=_ONE)
    assert moved == f"{tenant_prefix(_ONE)}/run1/abc123.mp4"


def test_two_accounts_never_derive_the_same_destination() -> None:
    one = destination_for("abc.mp4", account_id=_ONE)
    assert one != destination_for("abc.mp4", account_id=_TWO)


def test_a_gs_uri_and_a_bare_name_migrate_to_the_same_place() -> None:
    bare = destination_for("abc.mp4", account_id=_ONE)
    assert destination_for(f"gs://{_BUCKET}/abc.mp4", account_id=_ONE) == bare


def test_an_object_already_in_account_space_is_not_moved_again() -> None:
    with pytest.raises(MigrationError):
        destination_for(f"{tenant_prefix(_ONE)}/abc.mp4", account_id=_ONE)


@pytest.mark.parametrize(
    "name",
    ["../abc.mp4", "run/../../abc.mp4", "run//abc.mp4", "./abc.mp4", "run\\abc.mp4", "  "],
)
def test_a_name_that_is_not_a_plain_path_is_refused(name: str) -> None:
    with pytest.raises(MigrationError):
        destination_for(name, account_id=_ONE)


def test_a_refusal_does_not_repeat_the_object_it_refused() -> None:
    with pytest.raises(MigrationError) as raised:
        destination_for("../secret-place.mp4", account_id=_ONE)
    assert "secret-place" not in str(raised.value)


# --- the plan ------------------------------------------------------------


def test_every_untenanted_object_is_planned_for_this_account() -> None:
    plan = plan_migration(["a.mp4", "b.mp4", "run1/c.mp4"], account_id=_ONE)
    assert len(plan.moves) == 3
    assert all(move.destination.startswith(f"{tenant_prefix(_ONE)}/") for move in plan.moves)


def test_objects_this_account_already_owns_are_counted_not_moved() -> None:
    owned = f"{tenant_prefix(_ONE)}/a.mp4"
    plan = plan_migration([owned, "b.mp4"], account_id=_ONE)
    assert (len(plan.moves), plan.already_owned, plan.other_accounts) == (1, 1, 0)


def test_another_accounts_objects_are_left_alone_and_only_counted() -> None:
    plan = plan_migration([f"{tenant_prefix(_TWO)}/a.mp4", "b.mp4"], account_id=_ONE)
    assert (len(plan.moves), plan.already_owned, plan.other_accounts) == (1, 0, 1)
    assert plan.moves[0].source == "b.mp4"


def test_a_part_finished_migration_run_again_has_nothing_left_to_move() -> None:
    first = plan_migration(["a.mp4", "b.mp4"], account_id=_ONE)
    again = plan_migration([move.destination for move in first.moves], account_id=_ONE)
    assert again.moves == ()
    assert again.already_owned == 2


def test_an_object_under_the_tenant_root_with_no_account_stops_the_plan() -> None:
    with pytest.raises(MigrationError):
        plan_migration(["u/a.mp4"], account_id=_ONE)


def test_an_account_space_with_something_short_of_a_digest_stops_the_plan() -> None:
    with pytest.raises(MigrationError):
        plan_migration(["u/abc/a.mp4"], account_id=_ONE)


def test_one_climbing_name_stops_the_whole_plan_rather_than_being_dropped() -> None:
    with pytest.raises(MigrationError):
        plan_migration(["a.mp4", "../b.mp4"], account_id=_ONE)


def test_the_summary_says_how_many_and_never_which() -> None:
    plan = plan_migration(["a.mp4", f"{tenant_prefix(_TWO)}/b.mp4"], account_id=_ONE)
    summary = plan.summary()
    assert summary == {
        "prefix": tenant_prefix(_ONE),
        "objects": 2,
        "to_move": 1,
        "already_owned": 0,
        "other_accounts": 1,
    }
    assert "a.mp4" not in repr(summary)


def test_the_total_counts_every_object_the_listing_offered() -> None:
    plan = plan_migration(
        ["a.mp4", f"{tenant_prefix(_ONE)}/b.mp4", f"{tenant_prefix(_TWO)}/c.mp4"],
        account_id=_ONE,
    )
    assert plan.total == 3


def test_an_account_that_is_not_known_cannot_be_planned_for() -> None:
    with pytest.raises(TenancyError):
        plan_migration(["a.mp4"], account_id="   ")


# --- the move itself -----------------------------------------------------


def test_nothing_moves_without_approval() -> None:
    client = _Client(_legacy("a"))
    plan = plan_migration(["a.mp4"], account_id=_ONE)
    with pytest.raises(MigrationError):
        move_objects(_BUCKET, plan.moves, account_id=_ONE, client=client)
    assert set(client.store) == {"a.mp4"}


def test_a_move_copies_first_and_deletes_the_old_name_after() -> None:
    client = _Client(_legacy("a"))
    plan = plan_migration(["a.mp4"], account_id=_ONE)
    moved = move_objects(_BUCKET, plan.moves, account_id=_ONE, approved=True, client=client)
    assert moved == 1
    assert set(client.store) == {f"{tenant_prefix(_ONE)}/a.mp4"}


def test_the_bytes_that_arrive_are_the_bytes_that_left() -> None:
    client = _Client(_legacy("a"))
    plan = plan_migration(["a.mp4"], account_id=_ONE)
    move_objects(_BUCKET, plan.moves, account_id=_ONE, approved=True, client=client)
    assert client.store[f"{tenant_prefix(_ONE)}/a.mp4"] == "a"


def test_a_copy_that_did_not_arrive_leaves_the_old_object_in_place() -> None:
    client = _Client(_legacy("a"), copies_vanish=True)
    plan = plan_migration(["a.mp4"], account_id=_ONE)
    with pytest.raises(MigrationError):
        move_objects(_BUCKET, plan.moves, account_id=_ONE, approved=True, client=client)
    assert set(client.store) == {"a.mp4"}


def test_an_interrupted_move_resumes_without_copying_the_arrived_half_again() -> None:
    already = f"{tenant_prefix(_ONE)}/a.mp4"
    client = _Client({"a.mp4": "a", already: "a"})
    plan = plan_migration(["a.mp4"], account_id=_ONE)
    move_objects(_BUCKET, plan.moves, account_id=_ONE, approved=True, client=client)
    assert client.bucket(_BUCKET).copied == []
    assert set(client.store) == {already}


def test_a_destination_outside_this_account_is_refused_before_anything_copies() -> None:
    client = _Client(_legacy("a", "b"))
    forged = ObjectMove(source="b.mp4", destination=f"{tenant_prefix(_TWO)}/b.mp4")
    plan = plan_migration(["a.mp4"], account_id=_ONE)
    with pytest.raises(MigrationError):
        move_objects(_BUCKET, (*plan.moves, forged), account_id=_ONE, approved=True, client=client)
    assert set(client.store) == {"a.mp4", "b.mp4"}


def test_a_destination_this_account_did_not_derive_is_refused() -> None:
    client = _Client(_legacy("a"))
    renamed = ObjectMove(source="a.mp4", destination=f"{tenant_prefix(_ONE)}/elsewhere/a.mp4")
    with pytest.raises(MigrationError):
        move_objects(_BUCKET, [renamed], account_id=_ONE, approved=True, client=client)
    assert set(client.store) == {"a.mp4"}


def test_a_source_already_in_account_space_is_refused_before_anything_copies() -> None:
    owned = f"{tenant_prefix(_ONE)}/a.mp4"
    client = _Client({owned: "a"})
    move = ObjectMove(source=owned, destination=f"{tenant_prefix(_ONE)}/{owned}")
    with pytest.raises(MigrationError):
        move_objects(_BUCKET, [move], account_id=_ONE, approved=True, client=client)
    assert set(client.store) == {owned}


def test_every_move_is_reported_as_it_lands() -> None:
    client = _Client(_legacy("a", "b"))
    seen: list[str] = []
    plan = plan_migration(["a.mp4", "b.mp4"], account_id=_ONE)
    move_objects(
        _BUCKET,
        plan.moves,
        account_id=_ONE,
        approved=True,
        client=client,
        on_moved=lambda move: seen.append(move.source),
    )
    assert seen == ["a.mp4", "b.mp4"]


def test_a_migration_needs_a_bucket_to_act_on() -> None:
    with pytest.raises(MigrationError):
        move_objects("  ", [], account_id=_ONE, approved=True, client=_Client())


# --- listing and the whole run -------------------------------------------


def test_the_listing_asks_for_the_whole_bucket_not_a_prefix() -> None:
    client = _Client(_legacy("a"))
    assert list_bucket_objects(_BUCKET, client=client) == ("a.mp4",)
    assert client.listed == [_BUCKET]


def test_a_listing_needs_a_bucket_to_look_in() -> None:
    with pytest.raises(MigrationError):
        list_bucket_objects("   ", client=_Client())


def test_unapproved_a_migration_lists_and_decides_and_stops() -> None:
    client = _Client(_legacy("a", "b"))
    plan = migrate_account(_BUCKET, account_id=_ONE, client=client)
    assert len(plan.moves) == 2
    assert set(client.store) == {"a.mp4", "b.mp4"}


def test_approved_a_migration_adopts_every_untenanted_object() -> None:
    client = _Client({**_legacy("a", "b"), f"{tenant_prefix(_TWO)}/c.mp4": "c"})
    plan = migrate_account(_BUCKET, account_id=_ONE, approved=True, client=client)
    assert (len(plan.moves), plan.other_accounts) == (2, 1)
    assert set(client.store) == {
        f"{tenant_prefix(_ONE)}/a.mp4",
        f"{tenant_prefix(_ONE)}/b.mp4",
        f"{tenant_prefix(_TWO)}/c.mp4",
    }


def test_a_second_approved_run_is_a_no_op() -> None:
    client = _Client(_legacy("a"))
    migrate_account(_BUCKET, account_id=_ONE, approved=True, client=client)
    before = dict(client.store)
    plan = migrate_account(_BUCKET, account_id=_ONE, approved=True, client=client)
    assert plan.moves == ()
    assert client.store == before


def test_an_empty_bucket_is_a_plan_with_nothing_in_it() -> None:
    plan = migrate_account(_BUCKET, account_id=_ONE, approved=True, client=_Client())
    assert plan.total == 0
    assert plan.summary()["to_move"] == 0
