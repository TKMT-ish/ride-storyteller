"""Bring a new day's GPX and footage in from the console, safely.

The runbook's first two steps -- propose the clock offset, then build the
package -- were commands. This lets the console do them, which is what
makes "hand me a different day's clips" a thing the page can take.

Two things are guarded, and both are about what a browser is allowed to
point the server at.

Paths come from a form. They are accepted only inside one intake root
(`private-media/input` by default), resolved, and refused if anything on
the way is a symlink. A browser must not be able to make this process read
an arbitrary file on the machine by naming it. The package is written only
under the work root, under a name that is a plain word.

The clock offset is the one judgement a person makes about a ride, and the
proposal exists so they can make it with evidence in front of them. It is
confirmed the same way the spend is: the request carries the number that
was proposed, and a number that was not proposed is not confirmed. What
was shown is what is agreed to.

Everything here is local. Proposing reads metadata and the track; building
the package catalogues recordings and writes JSON. No video is decoded and
nothing is sent. The proposal's own payload is counts and seconds, so it
can go to a browser as it is.
"""

from __future__ import annotations

import os
import re
from dataclasses import dataclass
from pathlib import Path

from app.clock_offset import ClockOffsetError, ClockOffsetProposal, propose_clock_offset
from app.local_pipeline import prepare_local_review_package

PRIVATE_JOURNEY_INTAKE_SCHEMA_VERSION = "private-journey-intake-v1"

INTAKE_ROOT_ENV = "RIDE_PRIVATE_INTAKE_ROOT"
WORK_ROOT_ENV = "RIDE_PRIVATE_WORK_ROOT"
DEFAULT_INTAKE_ROOT = Path("private-media/input")
DEFAULT_WORK_ROOT = Path("private-media/work")

# A package is named by a plain word: letters, digits, dash, underscore.
_PACKAGE_NAME = re.compile(r"\A[A-Za-z0-9][A-Za-z0-9_-]{0,63}\Z")

# Fixed, non-identifying: why a request was refused.
REASON_PATH_OUTSIDE_INTAKE = "path_outside_the_intake_root"
REASON_PATH_UNSAFE = "path_is_a_symlink_or_missing"
REASON_GPX_NOT_A_FILE = "gpx_is_not_a_file"
REASON_VIDEO_NOT_A_DIRECTORY = "video_root_is_not_a_directory"
REASON_NAME_UNSAFE = "package_name_is_not_a_plain_word"
REASON_PACKAGE_EXISTS = "package_already_exists"
REASON_OFFSET_NOT_PROPOSED = "offset_was_not_the_one_proposed"
REASON_OFFSET_AMBIGUOUS_UNCHOSEN = "offset_is_ambiguous_and_none_was_chosen"
REASON_NO_RECORDING_IN_RIDE = "no_recording_inside_the_ride"
REASON_TARGET_DURATION_INVALID = "target_duration_invalid"
REASON_PACKAGE_MISSING = "package_does_not_exist"


class IntakeRefused(RuntimeError):
    """A request the console must answer with a reason, not act on."""

    def __init__(self, reason: str) -> None:
        super().__init__(reason)
        self.reason = reason


@dataclass(frozen=True)
class IntakeRoots:
    """Where footage may be read from and where packages may be written."""

    intake_root: Path
    work_root: Path

    @classmethod
    def from_environment(cls) -> "IntakeRoots":
        intake = Path(os.environ.get(INTAKE_ROOT_ENV, "") or DEFAULT_INTAKE_ROOT)
        work = Path(os.environ.get(WORK_ROOT_ENV, "") or DEFAULT_WORK_ROOT)
        return cls(intake_root=intake.expanduser().resolve(), work_root=work.expanduser().resolve())


def _inside(root: Path, raw: object) -> Path:
    """A path under the root, with nothing on the way that is a symlink."""
    text = str(raw or "").strip()
    if not text:
        raise IntakeRefused(REASON_PATH_UNSAFE)
    candidate = Path(text)
    if not candidate.is_absolute():
        candidate = root / candidate
    # Walk the path as it was given, not as it resolves: a symlink on the
    # way is refused even when it lands inside the root, because what it
    # points at can be changed later by whoever can write the link.
    walk = Path(candidate.anchor)
    for part in candidate.parts[1:]:
        walk = walk / part
        if walk.is_symlink():
            raise IntakeRefused(REASON_PATH_UNSAFE)
    try:
        resolved = candidate.resolve(strict=True)
    except (OSError, RuntimeError):
        raise IntakeRefused(REASON_PATH_UNSAFE) from None
    if resolved != root and root not in resolved.parents:
        raise IntakeRefused(REASON_PATH_OUTSIDE_INTAKE)
    return resolved


def check_sources(roots: IntakeRoots, *, gpx: object, video_root: object) -> tuple[Path, Path]:
    """The GPX file and the footage directory, both inside the intake root."""
    gpx_path = _inside(roots.intake_root, gpx)
    if not gpx_path.is_file():
        raise IntakeRefused(REASON_GPX_NOT_A_FILE)
    video_path = _inside(roots.intake_root, video_root)
    if not video_path.is_dir():
        raise IntakeRefused(REASON_VIDEO_NOT_A_DIRECTORY)
    return gpx_path, video_path


def check_package_name(roots: IntakeRoots, name: object) -> Path:
    """Where the new package goes: under the work root, by a plain word."""
    text = str(name or "").strip()
    if not _PACKAGE_NAME.match(text):
        raise IntakeRefused(REASON_NAME_UNSAFE)
    destination = roots.work_root / text
    if destination.exists() or destination.is_symlink():
        raise IntakeRefused(REASON_PACKAGE_EXISTS)
    return destination


def select_package(roots: IntakeRoots, name: object) -> Path:
    """An existing package under the work root, by its plain-word name."""
    text = str(name or "").strip()
    if not _PACKAGE_NAME.match(text):
        raise IntakeRefused(REASON_NAME_UNSAFE)
    candidate = roots.work_root / text
    if candidate.is_symlink() or not candidate.is_dir():
        raise IntakeRefused(REASON_PACKAGE_MISSING)
    return candidate.resolve()


def list_packages(roots: IntakeRoots) -> list[str]:
    """The plain-word names of the packages under the work root, and nothing else.

    A package is a directory the console can read: it has the inputs and the
    catalogue. The work root also holds research runs, review clips and the
    like, and a switcher that offered those would offer things that are not
    rides.
    """
    if not roots.work_root.is_dir():
        return []
    return sorted(
        entry.name
        for entry in roots.work_root.iterdir()
        if entry.is_dir()
        and not entry.is_symlink()
        and _PACKAGE_NAME.match(entry.name)
        and (entry / "local-pipeline-inputs.json").is_file()
        and (entry / "local-video-catalog.json").is_file()
    )


def propose(roots: IntakeRoots, *, gpx: object, video_root: object) -> dict[str, object]:
    """Say what the clock offset should be, with the evidence. Reads metadata only."""
    gpx_path, video_path = check_sources(roots, gpx=gpx, video_root=video_root)
    try:
        proposal = propose_clock_offset(gpx_path, video_path)
    except ClockOffsetError:
        raise IntakeRefused(REASON_NO_RECORDING_IN_RIDE) from None
    payload = proposal.to_dict()
    payload["schema_version"] = PRIVATE_JOURNEY_INTAKE_SCHEMA_VERSION
    return payload


def confirm_offset(proposal: ClockOffsetProposal, offset_s: object) -> float:
    """The gate: the offset confirmed is one that was proposed.

    An unambiguous proposal has one answer; an ambiguous one has several,
    and the person picks. Either way a number that was never on the table
    is not a confirmation of anything.
    """
    try:
        chosen = float(offset_s)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        raise IntakeRefused(REASON_OFFSET_NOT_PROPOSED) from None
    offered = {proposal.best.offset_s, *(c.offset_s for c in proposal.runners_up)}
    if chosen not in offered:
        raise IntakeRefused(REASON_OFFSET_NOT_PROPOSED)
    return chosen


def create_package(
    roots: IntakeRoots,
    *,
    gpx: object,
    video_root: object,
    name: object,
    offset_s: object,
    target_duration_s: object = 300.0,
) -> Path:
    """Build the package for a new day, once its clock offset is confirmed.

    The proposal is recomputed here rather than trusted from the request,
    so the offset confirmed is checked against what the evidence actually
    says now, not against whatever a page remembered.
    """
    gpx_path, video_path = check_sources(roots, gpx=gpx, video_root=video_root)
    destination = check_package_name(roots, name)
    try:
        target = float(target_duration_s)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        raise IntakeRefused(REASON_TARGET_DURATION_INVALID) from None
    if not 30.0 <= target <= 3600.0:
        raise IntakeRefused(REASON_TARGET_DURATION_INVALID)
    try:
        proposal = propose_clock_offset(gpx_path, video_path)
    except ClockOffsetError:
        raise IntakeRefused(REASON_NO_RECORDING_IN_RIDE) from None
    confirmed = confirm_offset(proposal, offset_s)

    prepare_local_review_package(
        gpx_path,
        video_path,
        destination,
        video_to_gps_offset_s=confirmed,
        clock_offset_confirmed=True,
        target_duration_s=target,
        # The judged path needs the catalogue and the inputs; cutting review
        # clips for every candidate is minutes of FFmpeg nobody will watch.
        extract_reviews=False,
    )
    return destination
