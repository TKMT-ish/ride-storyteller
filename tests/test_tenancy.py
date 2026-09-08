"""One account's objects must be unreachable from another account."""

from __future__ import annotations

import pytest

from app.tenancy import (
    TENANT_ROOT,
    TenancyError,
    object_path,
    owns_object,
    require_own_object,
    scoped_prefix,
    tenant_prefix,
)

_ONE = "rider-one@example.com"
_TWO = "rider-two@example.com"


def test_a_prefix_is_derived_from_the_account_and_is_stable() -> None:
    assert tenant_prefix(_ONE) == tenant_prefix(_ONE)
    assert tenant_prefix(_ONE) != tenant_prefix(_TWO)
    assert tenant_prefix(_ONE).startswith(f"{TENANT_ROOT}/")


def test_a_prefix_never_carries_the_account_itself() -> None:
    prefix = tenant_prefix(_ONE)
    assert _ONE not in prefix
    assert "rider" not in prefix.removeprefix(f"{TENANT_ROOT}/")
    assert "example.com" not in prefix


def test_surrounding_whitespace_does_not_make_a_second_account() -> None:
    assert tenant_prefix(f"  {_ONE}  ") == tenant_prefix(_ONE)


def test_an_account_has_to_be_known() -> None:
    with pytest.raises(TenancyError):
        tenant_prefix("   ")


def test_an_object_is_read_the_same_named_or_addressed() -> None:
    assert object_path("gs://rides/u/abc/window.mp4") == "u/abc/window.mp4"
    assert object_path("u/abc/window.mp4") == "u/abc/window.mp4"
    assert object_path("/u/abc/window.mp4") == "u/abc/window.mp4"


def test_a_bucket_without_an_object_is_refused() -> None:
    for uri in ("gs://rides", "gs://rides/", "  "):
        with pytest.raises(TenancyError):
            object_path(uri)


def test_an_account_owns_what_is_under_its_own_prefix() -> None:
    uri = f"gs://rides/{tenant_prefix(_ONE)}/window.mp4"
    assert owns_object(uri, account_id=_ONE)
    assert require_own_object(uri, account_id=_ONE).endswith("window.mp4")


def test_another_account_is_refused_the_same_object() -> None:
    uri = f"gs://rides/{tenant_prefix(_ONE)}/window.mp4"
    assert not owns_object(uri, account_id=_TWO)
    with pytest.raises(TenancyError):
        require_own_object(uri, account_id=_TWO)


def test_a_refusal_does_not_repeat_the_object_it_refused() -> None:
    uri = f"gs://rides/{tenant_prefix(_ONE)}/window.mp4"
    with pytest.raises(TenancyError) as raised:
        require_own_object(uri, account_id=_TWO)
    assert "window.mp4" not in str(raised.value)
    assert tenant_prefix(_ONE) not in str(raised.value)


def test_a_longer_prefix_starting_with_the_same_text_is_not_the_same_account() -> None:
    # A raw text comparison would let `u/abcd` claim `u/abcdef/...`.
    mine = tenant_prefix(_ONE)
    assert not owns_object(f"gs://rides/{mine}extra/window.mp4", account_id=_ONE)


def test_the_prefix_itself_is_not_an_object() -> None:
    assert not owns_object(f"gs://rides/{tenant_prefix(_ONE)}", account_id=_ONE)


def test_a_name_that_climbs_is_refused_rather_than_resolved() -> None:
    mine = tenant_prefix(_ONE)
    for name in (
        f"{mine}/../{tenant_prefix(_TWO)}/window.mp4",
        f"{mine}/./window.mp4",
        f"{mine}//window.mp4",
        f"{mine}\\window.mp4",
    ):
        assert not owns_object(f"gs://rides/{name}", account_id=_ONE)


def test_an_object_with_no_account_space_at_all_is_refused() -> None:
    assert not owns_object("gs://rides/window.mp4", account_id=_ONE)


def test_a_run_prefix_goes_underneath_the_account_never_beside_it() -> None:
    scoped = scoped_prefix(_ONE, prefix="runs/one")
    assert scoped == f"{tenant_prefix(_ONE)}/runs/one"
    assert owns_object(f"gs://rides/{scoped}/window.mp4", account_id=_ONE)
    assert not owns_object(f"gs://rides/{scoped}/window.mp4", account_id=_TWO)


def test_a_run_prefix_cannot_name_its_way_out() -> None:
    for prefix in ("../other", "a/../../b", "Runs Two", ""):
        if prefix == "":
            assert scoped_prefix(_ONE, prefix=prefix) == tenant_prefix(_ONE)
            continue
        with pytest.raises(TenancyError):
            scoped_prefix(_ONE, prefix=prefix)
