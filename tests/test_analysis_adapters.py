"""Synthetic-fixture tests for the uploader and analyser handed to a run.

Nothing here connects to Google. The uploader is given a stub client and the
analyser a stub judge, so the mapping between a window and the file that
stands for it -- the part that would quietly cut the wrong footage -- is
exercised without spending anything.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from app.analysis_adapters import (
    AnalysisAdapterError,
    judge_with,
    object_name_for,
    upload_to_bucket,
)
from app.analysis_run import AnalysisCandidate
from app.contracts import MediaAsset, VideoAnalysis

_CANDIDATE = AnalysisCandidate(
    event_id="footage-0123456789abcdef",
    asset_id="asset-synthetic-1",
    start_offset_s=1_830.0,
    end_offset_s=1_842.0,
)


class _Judge:
    """Stand in for Gemini, recording what it was asked about."""

    def __init__(self) -> None:
        self.asked: list[tuple[MediaAsset, float, float]] = []

    def analyze(self, asset: MediaAsset, *, start_s: float, end_s: float) -> VideoAnalysis:
        self.asked.append((asset, start_s, end_s))
        return VideoAnalysis(
            asset_id=asset.asset_id,
            start_offset_s=start_s,
            end_offset_s=end_s,
            visual_description="A mountain road",
            road_type="mountain road",
            scenery_tags=("trees",),
            weather_visible="clear",
            visual_interest_score=0.8,
            story_relevance_score=0.7,
            confidence=0.9,
            analysis_provider="gemini",
        )


# --- the window, and the file that stands for it ----------------------------


def test_the_model_is_asked_about_the_whole_proxy_not_the_original_offsets() -> None:
    """The proxy is a standalone clip that starts at zero.

    Asking about 1830s of a twelve-second clip asks about nothing.
    """
    judge = _Judge()

    judge_with(judge)("gs://bucket/clip.mp4", _CANDIDATE)

    asset, start_s, end_s = judge.asked[0]
    assert (start_s, end_s) == (0.0, 12.0)
    assert asset.source_uri == "gs://bucket/clip.mp4"
    assert asset.duration_s == 12.0


def test_the_judgement_carries_the_offsets_the_film_will_cut_at() -> None:
    """Downstream, offsets mean a position in the ride's own recording."""
    judged = judge_with(_Judge())("gs://bucket/clip.mp4", _CANDIDATE)

    assert judged.start_offset_s == 1_830.0
    assert judged.end_offset_s == 1_842.0
    assert judged.asset_id == "asset-synthetic-1"


def test_what_the_model_said_is_kept_unchanged() -> None:
    judged = judge_with(_Judge())("gs://bucket/clip.mp4", _CANDIDATE)

    assert judged.visual_description == "A mountain road"
    assert judged.road_type == "mountain road"
    assert judged.visual_interest_score == 0.8
    assert judged.analysis_provider == "gemini"


def test_a_window_is_never_judged_without_an_uploaded_object() -> None:
    with pytest.raises(AnalysisAdapterError, match="without an uploaded object"):
        judge_with(_Judge())("", _CANDIDATE)


# --- what a bucket listing is allowed to say --------------------------------


def test_an_object_is_named_after_the_window_hash_and_nothing_else() -> None:
    """Not the file name, not the capture time: both identify a rider."""
    name = object_name_for(_CANDIDATE)

    assert name == "footage-0123456789abcdef.mp4"
    for forbidden in ("GH01", ".MP4", "2026", _CANDIDATE.asset_id):
        assert forbidden not in name


def test_a_prefix_groups_a_ride_without_naming_it() -> None:
    named = object_name_for(_CANDIDATE, prefix="runs/2026")
    assert named == "runs/2026/footage-0123456789abcdef.mp4"
    assert object_name_for(_CANDIDATE, prefix="/runs/").startswith("runs/")


def test_an_identifier_that_is_not_safe_as_an_object_name_is_refused() -> None:
    for unsafe in ("../escape", "GH010042.MP4", "", "a/b"):
        with pytest.raises(AnalysisAdapterError, match="not safe to use"):
            object_name_for(
                AnalysisCandidate(
                    event_id=unsafe,
                    asset_id="asset-1",
                    start_offset_s=0.0,
                    end_offset_s=12.0,
                )
            )


# --- the uploader decides nothing -------------------------------------------


class _Blob:
    def __init__(self, name: str) -> None:
        self.name = name
        self.uploaded: tuple[str, str] | None = None

    def upload_from_filename(self, path: str, content_type: str) -> None:
        self.uploaded = (path, content_type)


class _Bucket:
    def __init__(self) -> None:
        self.blobs: list[_Blob] = []

    def blob(self, name: str) -> _Blob:
        made = _Blob(name)
        self.blobs.append(made)
        return made


class _Client:
    def __init__(self) -> None:
        self.buckets: dict[str, _Bucket] = {}

    def bucket(self, name: str) -> _Bucket:
        return self.buckets.setdefault(name, _Bucket())


def test_an_upload_puts_the_copy_in_the_bucket_and_returns_its_uri(tmp_path: Path) -> None:
    proxy = tmp_path / "clip.mp4"
    proxy.write_bytes(b"a small copy")
    client = _Client()

    uri = upload_to_bucket("rides", client=client)(proxy, _CANDIDATE)

    assert uri == "gs://rides/footage-0123456789abcdef.mp4"
    blob = client.buckets["rides"].blobs[0]
    assert blob.uploaded == (str(proxy), "video/mp4")


def test_the_uri_returned_is_the_one_the_analyser_will_read(tmp_path: Path) -> None:
    proxy = tmp_path / "clip.mp4"
    proxy.write_bytes(b"a small copy")
    judge = _Judge()

    uri = upload_to_bucket("rides", prefix="runs/one", client=_Client())(proxy, _CANDIDATE)
    judge_with(judge)(uri, _CANDIDATE)

    assert judge.asked[0][0].source_uri == "gs://rides/runs/one/footage-0123456789abcdef.mp4"


def test_a_missing_copy_is_not_uploaded(tmp_path: Path) -> None:
    with pytest.raises(AnalysisAdapterError, match="missing or is not a plain file"):
        upload_to_bucket("rides", client=_Client())(tmp_path / "gone.mp4", _CANDIDATE)


def test_a_symlinked_copy_is_refused(tmp_path: Path) -> None:
    real = tmp_path / "real.mp4"
    real.write_bytes(b"a small copy")
    link = tmp_path / "link.mp4"
    link.symlink_to(real)

    with pytest.raises(AnalysisAdapterError, match="missing or is not a plain file"):
        upload_to_bucket("rides", client=_Client())(link, _CANDIDATE)


def test_an_uploader_without_a_bucket_is_refused() -> None:
    with pytest.raises(AnalysisAdapterError, match="needs a bucket"):
        upload_to_bucket("   ")


def test_building_the_adapters_connects_to_nothing(tmp_path: Path) -> None:
    """Only calling them does, and only with a client they were given."""
    upload_to_bucket("rides")
    judge_with(_Judge())


def test_importing_this_module_cannot_reach_google() -> None:
    import ast

    source = Path("app/analysis_adapters.py").read_text(encoding="utf-8")
    tree = ast.parse(source)
    top_level = [node for node in tree.body if isinstance(node, (ast.Import, ast.ImportFrom))]
    names = [
        alias.name for node in top_level if isinstance(node, ast.Import) for alias in node.names
    ] + [node.module or "" for node in top_level if isinstance(node, ast.ImportFrom)]

    assert not any(name.startswith("google") for name in names)


# --- the two adapters together fit what a run asks for ----------------------


def test_the_adapters_match_the_signatures_run_analysis_expects(tmp_path: Path) -> None:
    from app.analysis_run import run_analysis

    proxy = tmp_path / "clip.mp4"
    proxy.write_bytes(b"a small copy")

    upload = upload_to_bucket("rides", client=_Client())
    analyse = judge_with(_Judge())

    # Exactly the call shapes run_analysis makes.
    uri = upload(proxy, _CANDIDATE)
    judged = analyse(uri, _CANDIDATE)

    assert run_analysis is not None
    assert judged.start_offset_s == _CANDIDATE.start_offset_s


# --- one account's objects, and no other's ----------------------------------


class _Transport:
    """Stand in for the ranking call, recording what it was shown."""

    def __init__(self) -> None:
        self.shown: list[list[str]] = []

    def rank_clips(self, *, source_uris: list[str], mime_type: str, prompt: str) -> list[str]:
        self.shown.append(list(source_uris))
        return [chr(ord("A") + index) for index in range(len(source_uris))]


def test_an_account_uploads_under_its_own_prefix(tmp_path: Path) -> None:
    from app.tenancy import tenant_prefix

    proxy = tmp_path / "clip.mp4"
    proxy.write_bytes(b"a small copy")

    uri = upload_to_bucket("rides", account_id="rider-one", client=_Client())(proxy, _CANDIDATE)

    assert uri.startswith(f"gs://rides/{tenant_prefix('rider-one')}/")
    assert uri.endswith("/footage-0123456789abcdef.mp4")


def test_a_run_prefix_stays_underneath_the_account(tmp_path: Path) -> None:
    from app.tenancy import tenant_prefix

    proxy = tmp_path / "clip.mp4"
    proxy.write_bytes(b"a small copy")

    upload = upload_to_bucket("rides", prefix="runs/one", account_id="rider-one", client=_Client())

    assert upload(proxy, _CANDIDATE) == (
        f"gs://rides/{tenant_prefix('rider-one')}/runs/one/footage-0123456789abcdef.mp4"
    )


def test_judging_refuses_an_object_belonging_to_another_account() -> None:
    from app.tenancy import TenancyError, tenant_prefix

    judge = _Judge()
    theirs = f"gs://rides/{tenant_prefix('rider-two')}/footage-0123456789abcdef.mp4"

    with pytest.raises(TenancyError):
        judge_with(judge, account_id="rider-one")(theirs, _CANDIDATE)

    assert judge.asked == []


def test_judging_an_account_s_own_object_still_goes_through(tmp_path: Path) -> None:
    proxy = tmp_path / "clip.mp4"
    proxy.write_bytes(b"a small copy")
    judge = _Judge()

    uri = upload_to_bucket("rides", account_id="rider-one", client=_Client())(proxy, _CANDIDATE)
    judge_with(judge, account_id="rider-one")(uri, _CANDIDATE)

    assert judge.asked[0][0].source_uri == uri


def test_ranking_refuses_a_group_with_one_foreign_object() -> None:
    from app.analysis_adapters import rank_with
    from app.tenancy import TenancyError, tenant_prefix

    transport = _Transport()
    mine = tenant_prefix("rider-one")
    theirs = tenant_prefix("rider-two")
    compare = rank_with(transport, prompt="order these", account_id="rider-one")

    with pytest.raises(TenancyError):
        compare([("one", f"gs://rides/{mine}/one.mp4"), ("two", f"gs://rides/{theirs}/two.mp4")])

    assert transport.shown == []


def test_ranking_an_account_s_own_group_still_goes_through() -> None:
    from app.analysis_adapters import rank_with
    from app.tenancy import tenant_prefix

    transport = _Transport()
    mine = tenant_prefix("rider-one")
    compare = rank_with(transport, prompt="order these", account_id="rider-one")

    ordered = compare(
        [("one", f"gs://rides/{mine}/one.mp4"), ("two", f"gs://rides/{mine}/two.mp4")]
    )

    assert ordered == ["one", "two"]
    assert len(transport.shown[0]) == 2


def test_without_an_account_nothing_changes_for_the_single_rider(tmp_path: Path) -> None:
    """The existing single-user path is untouched until an account is given."""
    proxy = tmp_path / "clip.mp4"
    proxy.write_bytes(b"a small copy")

    uri = upload_to_bucket("rides", client=_Client())(proxy, _CANDIDATE)

    assert uri == "gs://rides/footage-0123456789abcdef.mp4"
    judge_with(_Judge())(uri, _CANDIDATE)
