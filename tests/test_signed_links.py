"""A link is a capability: check the account first, and let it die early."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta, timezone

import pytest

from app.retention import DEFAULT_RETENTION_DAYS, StoredObject
from app.signed_links import (
    DEFAULT_LINK_SECONDS,
    MAX_LINK_SECONDS,
    SignedLink,
    SignedLinkError,
    link_lifetime,
    sign_object,
    sign_objects,
)
from app.tenancy import tenant_prefix

_ONE = "rider-one@example.com"
_TWO = "rider-two@example.com"
_BUCKET = "ride-proxies"
_NOW = datetime(2026, 9, 9, 3, 0, tzinfo=UTC)


class _Blob:
    def __init__(self, recorder: list[dict[str, object]], name: str) -> None:
        self._recorder = recorder
        self.name = name

    def generate_signed_url(self, **kwargs: object) -> str:
        self._recorder.append({"name": self.name, **kwargs})
        return f"https://storage.example/{self.name}?sig=deadbeef"


class _Bucket:
    def __init__(self, recorder: list[dict[str, object]], name: str) -> None:
        self._recorder = recorder
        self.name = name

    def blob(self, name: str) -> _Blob:
        return _Blob(self._recorder, name)


class _Client:
    """Enough of a GCS client to sign, and to remember what it was asked."""

    def __init__(self) -> None:
        self.signed: list[dict[str, object]] = []

    def bucket(self, name: str) -> _Bucket:
        return _Bucket(self.signed, name)


class _FailingClient(_Client):
    def __init__(self, error: Exception) -> None:
        super().__init__()
        self._error = error

    def bucket(self, name: str) -> _Bucket:
        raise self._error


def _own(account_id: str, leaf: str = "abc123.mp4") -> StoredObject:
    return StoredObject(name=f"{tenant_prefix(account_id)}/{leaf}", uploaded_at=_NOW)


# --- the ownership check happens before a signature exists -------------------


def test_signs_an_object_inside_the_accounts_own_prefix() -> None:
    client = _Client()
    link = sign_object(_BUCKET, _own(_ONE), account_id=_ONE, now=_NOW, client=client)
    assert link.url.startswith("https://storage.example/")
    assert len(client.signed) == 1


def test_refuses_another_accounts_object_without_signing_it() -> None:
    client = _Client()
    with pytest.raises(SignedLinkError):
        sign_object(_BUCKET, _own(_TWO), account_id=_ONE, now=_NOW, client=client)
    assert client.signed == []


def test_refusal_does_not_repeat_the_object_it_refused() -> None:
    stored = _own(_TWO, leaf="a-window-nobody-should-see.mp4")
    with pytest.raises(SignedLinkError) as raised:
        sign_object(_BUCKET, stored, account_id=_ONE, now=_NOW, client=_Client())
    message = str(raised.value)
    assert "a-window-nobody-should-see" not in message
    assert tenant_prefix(_TWO) not in message


def test_refuses_an_object_outside_the_tenant_root() -> None:
    stored = StoredObject(name="abc123.mp4", uploaded_at=_NOW)
    with pytest.raises(SignedLinkError):
        sign_object(_BUCKET, stored, account_id=_ONE, now=_NOW, client=_Client())


def test_refuses_a_name_that_climbs_out_of_the_prefix() -> None:
    stored = StoredObject(
        name=f"{tenant_prefix(_ONE)}/../{tenant_prefix(_TWO)}/x.mp4", uploaded_at=_NOW
    )
    with pytest.raises(SignedLinkError):
        sign_object(_BUCKET, stored, account_id=_ONE, now=_NOW, client=_Client())


def test_accepts_a_gs_uri_for_the_same_object() -> None:
    client = _Client()
    stored = StoredObject(name=f"gs://{_BUCKET}/{tenant_prefix(_ONE)}/abc123.mp4", uploaded_at=_NOW)
    sign_object(_BUCKET, stored, account_id=_ONE, now=_NOW, client=client)
    assert client.signed[0]["name"] == f"{tenant_prefix(_ONE)}/abc123.mp4"


def test_signing_needs_a_bucket() -> None:
    with pytest.raises(SignedLinkError):
        sign_object("  ", _own(_ONE), account_id=_ONE, now=_NOW, client=_Client())


def test_an_unknown_account_cannot_sign() -> None:
    with pytest.raises(SignedLinkError):
        sign_object(_BUCKET, _own(_ONE), account_id="  ", now=_NOW, client=_Client())


# --- reads only -------------------------------------------------------------


def test_the_signature_is_a_v4_get() -> None:
    client = _Client()
    sign_object(_BUCKET, _own(_ONE), account_id=_ONE, now=_NOW, client=client)
    assert client.signed[0]["method"] == "GET"
    assert client.signed[0]["version"] == "v4"


def test_sign_object_takes_no_method_argument() -> None:
    with pytest.raises(TypeError):
        sign_object(  # type: ignore[call-arg]
            _BUCKET, _own(_ONE), account_id=_ONE, now=_NOW, client=_Client(), method="PUT"
        )


# --- a link never outlives the object ---------------------------------------


def test_a_fresh_object_gets_the_full_requested_life() -> None:
    assert link_lifetime(now=_NOW, uploaded_at=_NOW) == DEFAULT_LINK_SECONDS


def test_the_life_is_clamped_to_what_retention_leaves() -> None:
    uploaded = _NOW - timedelta(days=DEFAULT_RETENTION_DAYS) + timedelta(seconds=90)
    assert link_lifetime(now=_NOW, uploaded_at=uploaded) == 90


def test_the_signature_carries_the_clamped_life_not_the_requested_one() -> None:
    client = _Client()
    uploaded = _NOW - timedelta(days=DEFAULT_RETENTION_DAYS) + timedelta(seconds=90)
    link = sign_object(
        _BUCKET,
        StoredObject(name=f"{tenant_prefix(_ONE)}/abc123.mp4", uploaded_at=uploaded),
        account_id=_ONE,
        now=_NOW,
        client=client,
    )
    assert link.lifetime_seconds == 90
    assert client.signed[0]["expiration"] == timedelta(seconds=90)
    assert link.expires_at == _NOW + timedelta(seconds=90)


def test_an_object_at_its_deadline_is_not_linkable() -> None:
    uploaded = _NOW - timedelta(days=DEFAULT_RETENTION_DAYS)
    with pytest.raises(SignedLinkError):
        link_lifetime(now=_NOW, uploaded_at=uploaded)


def test_an_object_past_its_deadline_is_not_linkable() -> None:
    uploaded = _NOW - timedelta(days=DEFAULT_RETENTION_DAYS + 1)
    with pytest.raises(SignedLinkError):
        link_lifetime(now=_NOW, uploaded_at=uploaded)


def test_a_sub_second_remainder_is_treated_as_expired() -> None:
    uploaded = _NOW - timedelta(days=DEFAULT_RETENTION_DAYS) + timedelta(milliseconds=400)
    with pytest.raises(SignedLinkError):
        link_lifetime(now=_NOW, uploaded_at=uploaded)


def test_an_expired_object_is_never_signed() -> None:
    client = _Client()
    uploaded = _NOW - timedelta(days=DEFAULT_RETENTION_DAYS + 1)
    with pytest.raises(SignedLinkError):
        sign_object(
            _BUCKET,
            StoredObject(name=f"{tenant_prefix(_ONE)}/abc123.mp4", uploaded_at=uploaded),
            account_id=_ONE,
            now=_NOW,
            client=client,
        )
    assert client.signed == []


def test_a_shorter_retention_shortens_the_link_too() -> None:
    uploaded = _NOW - timedelta(days=1) + timedelta(seconds=120)
    assert link_lifetime(now=_NOW, uploaded_at=uploaded, retention_days=1) == 120


def test_a_retention_period_that_runs_backwards_is_refused() -> None:
    with pytest.raises(SignedLinkError):
        link_lifetime(now=_NOW, uploaded_at=_NOW, retention_days=-1)


def test_an_upload_time_without_a_timezone_cannot_be_signed() -> None:
    with pytest.raises(SignedLinkError):
        link_lifetime(now=_NOW, uploaded_at=datetime(2026, 9, 9, 3, 0))


# --- the ceiling ------------------------------------------------------------


def test_the_ceiling_is_minutes_not_days() -> None:
    assert MAX_LINK_SECONDS <= 3600
    assert DEFAULT_LINK_SECONDS <= MAX_LINK_SECONDS


def test_a_life_past_the_ceiling_is_refused() -> None:
    with pytest.raises(SignedLinkError):
        link_lifetime(now=_NOW, uploaded_at=_NOW, requested_seconds=MAX_LINK_SECONDS + 1)


def test_the_ceiling_itself_is_allowed() -> None:
    assert link_lifetime(now=_NOW, uploaded_at=_NOW, requested_seconds=MAX_LINK_SECONDS) == (
        MAX_LINK_SECONDS
    )


def test_a_zero_or_negative_life_is_refused() -> None:
    for seconds in (0, -1):
        with pytest.raises(SignedLinkError):
            link_lifetime(now=_NOW, uploaded_at=_NOW, requested_seconds=seconds)


def test_a_life_that_is_not_a_whole_number_of_seconds_is_refused() -> None:
    for seconds in (60.5, "60", True):
        with pytest.raises(SignedLinkError):
            link_lifetime(now=_NOW, uploaded_at=_NOW, requested_seconds=seconds)  # type: ignore[arg-type]


def test_signing_needs_a_timezone_aware_now() -> None:
    with pytest.raises(SignedLinkError):
        link_lifetime(now=datetime(2026, 9, 9, 3, 0), uploaded_at=_NOW)


def test_now_in_another_timezone_measures_the_same_life() -> None:
    tokyo = _NOW.astimezone(timezone(timedelta(hours=9)))
    assert link_lifetime(now=tokyo, uploaded_at=_NOW) == DEFAULT_LINK_SECONDS


# --- what a signer failure is allowed to say --------------------------------


def test_a_signer_failure_does_not_name_the_object() -> None:
    stored = _own(_ONE, leaf="a-window-nobody-should-see.mp4")
    client = _FailingClient(RuntimeError(f"no key for {stored.name}"))
    with pytest.raises(SignedLinkError) as raised:
        sign_object(_BUCKET, stored, account_id=_ONE, now=_NOW, client=client)
    assert "a-window-nobody-should-see" not in str(raised.value)
    assert "RuntimeError" in str(raised.value)


def test_a_signer_that_returns_nothing_is_a_failure() -> None:
    class _EmptyBlob(_Blob):
        def generate_signed_url(self, **kwargs: object) -> str:
            return "   "

    class _EmptyClient(_Client):
        def bucket(self, name: str) -> _Bucket:
            bucket = _Bucket(self.signed, name)
            bucket.blob = lambda blob_name: _EmptyBlob(self.signed, blob_name)  # type: ignore[method-assign]
            return bucket

    with pytest.raises(SignedLinkError):
        sign_object(_BUCKET, _own(_ONE), account_id=_ONE, now=_NOW, client=_EmptyClient())


# --- the returned value -----------------------------------------------------


def test_a_link_that_points_nowhere_is_not_a_link() -> None:
    with pytest.raises(SignedLinkError):
        SignedLink(url="  ", expires_at=_NOW, lifetime_seconds=60)


def test_an_expiry_without_a_timezone_is_refused() -> None:
    with pytest.raises(SignedLinkError):
        SignedLink(url="https://x", expires_at=datetime(2026, 9, 9), lifetime_seconds=60)


def test_a_link_shorter_than_a_second_is_refused() -> None:
    with pytest.raises(SignedLinkError):
        SignedLink(url="https://x", expires_at=_NOW, lifetime_seconds=0)


# --- several at once --------------------------------------------------------


def test_signs_every_object_the_account_owns() -> None:
    client = _Client()
    stored = [_own(_ONE, leaf=f"{index:016x}.mp4") for index in range(5)]
    links = sign_objects(_BUCKET, stored, account_id=_ONE, now=_NOW, client=client)
    assert len(links) == 5
    assert len(client.signed) == 5


def test_one_foreign_object_refuses_the_whole_batch_before_signing_any() -> None:
    client = _Client()
    stored = [_own(_ONE, leaf=f"{index:016x}.mp4") for index in range(5)]
    stored.insert(3, _own(_TWO))
    with pytest.raises(SignedLinkError):
        sign_objects(_BUCKET, stored, account_id=_ONE, now=_NOW, client=client)
    assert client.signed == []


def test_an_empty_batch_signs_nothing_and_is_not_an_error() -> None:
    client = _Client()
    assert sign_objects(_BUCKET, [], account_id=_ONE, now=_NOW, client=client) == ()
    assert client.signed == []


def test_a_batch_of_tuples_works_the_same_as_a_list() -> None:
    client = _Client()
    stored = tuple(_own(_ONE, leaf=f"{index:016x}.mp4") for index in range(3))
    assert len(sign_objects(_BUCKET, stored, account_id=_ONE, now=_NOW, client=client)) == 3
