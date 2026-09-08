"""The two concrete things `run_analysis` needs handed to it.

`app.analysis_run` takes an uploader and an analyser and refuses to default
either, because both leave the machine and one of them bills. These are the
real implementations, kept apart from the run so that importing the run can
never reach Google. Both Google imports here are inside their factory: this
module can be imported, and its logic tested, on a machine with no cloud
libraries and no credentials.

The mapping between a window and the file that stands for it is the whole
job, and it is easy to get quietly wrong.

A candidate's offsets say where the window sits **in the ride's own
recording** -- 1830s to 1842s of a two-hour file -- and the film cuts from
the source at exactly those. But what was uploaded is a proxy: a standalone
twelve-second clip that starts at zero. Asking the model about 1830s to
1842s of a twelve-second clip asks about nothing.

So the two roles are separated. The model is asked about the whole proxy,
and the judgement it returns is stamped with the candidate's own offsets,
which are the ones that mean something to everything downstream. Conflating
them would not raise: it would return a judgement of the wrong footage, or
of no footage, and the film would be cut from it.
"""

from __future__ import annotations

import re
from collections.abc import Callable
from dataclasses import replace
from pathlib import Path

from app.analysis_run import AnalysisCandidate
from app.contracts import MediaAsset, VideoAnalysis
from app.tenancy import require_own_object, scoped_prefix
from app.video import VideoAnalyzer

PROXY_MIME_TYPE = "video/mp4"

# A candidate identifier is a hash of its own window (app.footage_candidates),
# so it names an object in a bucket without carrying a file name, a capture
# time, or anything else about the rider.
_SAFE_OBJECT_NAME = re.compile(r"\A[a-z0-9][a-z0-9._-]{0,127}\Z")


class AnalysisAdapterError(RuntimeError):
    """Raised when a window cannot be sent or judged as asked."""


def judge_with(
    analyzer: VideoAnalyzer, *, account_id: str | None = None
) -> Callable[[str, AnalysisCandidate], VideoAnalysis]:
    """An analyser for `run_analysis`, built on the project's own contract.

    The analyzer is asked about the whole proxy -- zero to its duration --
    because that is what the uploaded object contains. What comes back is
    re-stamped with the candidate's offsets into the ride's own recording,
    since those are the offsets the film cuts at.

    Given an account, the object is checked against that account's prefix
    before it is sent (`app.tenancy`). The URI arrives from a run that may
    have been restored, copied or edited, and judging is where the money is
    spent -- an object from another account would spend this one's budget
    to look at somebody else's ride.
    """

    def analyse(uri: str, candidate: AnalysisCandidate) -> VideoAnalysis:
        if not uri:
            raise AnalysisAdapterError("a window cannot be judged without an uploaded object")
        if account_id is not None:
            require_own_object(uri, account_id=account_id)
        if candidate.duration_s <= 0:
            raise AnalysisAdapterError("a window must cover a positive duration")
        proxy = MediaAsset(
            asset_id=candidate.asset_id,
            provider="ride-storyteller-proxy",
            name=f"{candidate.event_id}.mp4",
            mime_type=PROXY_MIME_TYPE,
            duration_s=candidate.duration_s,
            source_uri=uri,
        )
        judged = analyzer.analyze(proxy, start_s=0.0, end_s=candidate.duration_s)
        # The proxy's own clock is an implementation detail of sending it.
        return replace(
            judged,
            asset_id=candidate.asset_id,
            start_offset_s=candidate.start_offset_s,
            end_offset_s=candidate.end_offset_s,
        )

    return analyse


def object_name_for(candidate: AnalysisCandidate, *, prefix: str = "") -> str:
    """Name the uploaded object after the window's hash, and nothing else.

    Never after the recording's file name or its capture time. Those identify
    a rider and a place, and an object name is the one part of an upload that
    is read by people, logged, and kept in bucket listings long after the
    clip itself is gone.
    """
    if not _SAFE_OBJECT_NAME.match(candidate.event_id):
        raise AnalysisAdapterError("a window's identifier is not safe to use as an object name")
    cleaned = prefix.strip("/")
    if cleaned and not _SAFE_OBJECT_NAME.match(cleaned.replace("/", "-")):
        raise AnalysisAdapterError("an upload prefix must be a plain path segment")
    return f"{cleaned}/{candidate.event_id}.mp4" if cleaned else f"{candidate.event_id}.mp4"


def upload_to_bucket(
    bucket_name: str,
    *,
    prefix: str = "",
    account_id: str | None = None,
    client: object | None = None,
) -> Callable[[Path, AnalysisCandidate], str]:
    """An uploader for `run_analysis` that puts one proxy in one bucket.

    Building this does not connect; calling the returned function does. The
    Google import is deliberately inside, so nothing is reachable by import
    alone.

    The uploader decides nothing. Which window to send, and how small to make
    it, were settled before this is called -- re-deciding either here would
    put the same judgement in two places, and they would drift.

    Given an account, the caller's prefix is placed underneath that
    account's own (`app.tenancy.scoped_prefix`) rather than beside it, so a
    run can still be told apart from another run without being able to name
    its way out of the account it belongs to.
    """
    if not bucket_name.strip():
        raise AnalysisAdapterError("an upload needs a bucket to go to")
    upload_prefix = prefix if account_id is None else scoped_prefix(account_id, prefix=prefix)

    def upload(proxy: Path, candidate: AnalysisCandidate) -> str:
        if not proxy.is_file() or proxy.is_symlink():
            raise AnalysisAdapterError("a window's copy is missing or is not a plain file")
        name = object_name_for(candidate, prefix=upload_prefix)
        storage = client
        if storage is None:
            from google.cloud import storage as google_storage

            storage = google_storage.Client()
        blob = storage.bucket(bucket_name.strip()).blob(name)
        blob.upload_from_filename(str(proxy), content_type=PROXY_MIME_TYPE)
        return f"gs://{bucket_name.strip()}/{name}"

    return upload


def rank_with(
    transport: object, *, prompt: str, account_id: str | None = None
) -> Callable[[list[tuple[str, str]]], list[str]]:
    """A comparator for `rank_windows`, on the transport's ranking call.

    The transport labels clips A, B, C and answers in labels; this maps
    them back to the caller's identifiers, so nothing the model echoes is
    ever taken as an identifier.

    Given an account, every clip in the group is checked against that
    account's prefix first. Ranking sends several windows at once, so one
    foreign object among them would be enough.
    """

    def compare(pairs: list[tuple[str, str]]) -> list[str]:
        if not pairs:
            raise AnalysisAdapterError("a comparison needs windows to compare")
        uris = [uri for _, uri in pairs]
        if account_id is not None:
            for uri in uris:
                require_own_object(uri, account_id=account_id)
        labels = transport.rank_clips(  # type: ignore[attr-defined]
            source_uris=uris, mime_type=PROXY_MIME_TYPE, prompt=prompt
        )
        by_label = {chr(ord("A") + index): event_id for index, (event_id, _) in enumerate(pairs)}
        return [by_label[label] for label in labels]

    return compare
