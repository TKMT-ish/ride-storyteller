"""A package that can be cut into a film on someone else's machine.

The films are cut from the original recordings, and one day of them is 56.6
GiB: nobody can be handed that, and nobody should be handed footage that has
not been looked at. So a portable package carries, instead of the recordings,
one small clip per window the film uses -- the twelve seconds it needs, at
1080p, with the number plates blurred (`app.plate_blur`) -- and a map from
each window to its clip.

`film-sources.json` is that map, and it is also the allow-list: a package
that has one is cut from those windows and no others, so a re-plan on another
machine cannot reach for footage that was never shipped.

Nothing here decides what may be published. The caller passes the windows,
having checked them for faces; this writes what it is given.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path

from app.plate_blur import PlateBlurError, blur_until_clean

FILM_SOURCES_FILE_NAME = "film-sources.json"
FILM_SOURCES_SCHEMA_VERSION = "film-sources-v1"
FILM_SOURCES_DIRECTORY_NAME = "film-sources"
# The films are 1080p, so the clips are too: any more is thrown away by the cut.
CLIP_HEIGHT = 1080
# The films themselves run at about ten megabits a second, so the clips they
# are cut from are encoded to match: shipping sources better than the output
# is bytes nobody sees. At CRF 20 one day of them came to 3.5 GB; at 26, 0.9.
CLIP_CRF = 26


class PortablePackageError(RuntimeError):
    """Raised when a portable package cannot be built or read."""


@dataclass(frozen=True)
class PortableSource:
    """Where one window's footage lives in a portable package."""

    event_id: str
    file_name: str
    start_s: float = 0.0

    def __post_init__(self) -> None:
        if not self.event_id or not self.file_name:
            raise PortablePackageError("a portable source needs a window and a file")
        if Path(self.file_name).name != self.file_name:
            raise PortablePackageError("a portable source names a file, not a path")
        if self.start_s < 0:
            raise PortablePackageError("a portable source cannot start before its clip")


def write_film_sources(path: Path, sources: Sequence[PortableSource]) -> None:
    """Write the map, wholly or not at all."""
    if path.is_symlink():
        raise PortablePackageError("the film-sources path is unsafe")
    payload = {
        "schema_version": FILM_SOURCES_SCHEMA_VERSION,
        "sources": {
            source.event_id: {"file": source.file_name, "start_s": round(source.start_s, 3)}
            for source in sorted(sources, key=lambda item: item.event_id)
        },
    }
    temporary = path.with_name(f"{path.stem}.part{path.suffix}")
    temporary.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    os.replace(temporary, path)


def load_film_sources(path: Path) -> tuple[PortableSource, ...]:
    """The map, refused rather than guessed at when it is not what it claims."""
    if path.is_symlink() or not path.is_file():
        raise PortablePackageError("the film-sources map is unavailable")
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise PortablePackageError("the film-sources map is unreadable") from error
    if (
        not isinstance(payload, dict)
        or payload.get("schema_version") != FILM_SOURCES_SCHEMA_VERSION
    ):
        raise PortablePackageError("unsupported film-sources schema")
    sources = payload.get("sources")
    if not isinstance(sources, Mapping):
        raise PortablePackageError("the film-sources map is malformed")
    found: list[PortableSource] = []
    for event_id, item in sources.items():
        if not isinstance(item, Mapping):
            raise PortablePackageError("the film-sources map is malformed")
        try:
            found.append(
                PortableSource(
                    event_id=str(event_id),
                    file_name=str(item["file"]),
                    start_s=float(item.get("start_s", 0.0)),
                )
            )
        except (KeyError, TypeError, ValueError) as error:
            raise PortablePackageError("the film-sources map is malformed") from error
    return tuple(found)


def film_sources_or_none(package_directory: Path) -> tuple[PortableSource, ...] | None:
    """The package's own map, or None when it carries the recordings instead."""
    path = package_directory / FILM_SOURCES_FILE_NAME
    if not path.is_file():
        return None
    return load_film_sources(path)


def trim_command(
    source: Path, output: Path, *, start_s: float, duration_s: float, height: int = CLIP_HEIGHT
) -> tuple[str, ...]:
    """Cut one window out of a recording, at the height the film is cut at."""
    if duration_s <= 0:
        raise PortablePackageError("a clip must have a positive length")
    if start_s < 0:
        raise PortablePackageError("a clip cannot start before its recording")
    return (
        "ffmpeg", "-hide_banner", "-loglevel", "error", "-y",
        "-ss", f"{start_s:.3f}", "-i", str(source), "-t", f"{duration_s:.3f}",
        "-vf", f"scale=-2:{height}",
        "-c:v", "libx264", "-preset", "medium", "-crf", str(CLIP_CRF),
        "-pix_fmt", "yuv420p", "-an",
        str(output),
    )  # fmt: skip


def build_portable_sources(
    windows: Sequence[tuple[str, Path, float, float]],
    out_directory: Path,
    *,
    probe_path: Path,
    work: Path,
    blur: bool = True,
    fps: float = 20.0,
    passes: int = 3,
    runner: Callable[..., subprocess.CompletedProcess[str]] = subprocess.run,
) -> tuple[PortableSource, ...]:
    """Cut and blur one clip per window, and return the map to write.

    `windows` are `(event_id, recording, start_s, duration_s)`. Each clip is
    trimmed from the recording and then passed through the plate blur, so what
    is handed over has been looked at, not merely copied.
    """
    out_directory.mkdir(parents=True, exist_ok=True)
    work.mkdir(parents=True, exist_ok=True)
    built: list[PortableSource] = []
    for event_id, recording, start_s, duration_s in windows:
        if not recording.is_file() or recording.is_symlink():
            raise PortablePackageError("a window names a recording that is not there")
        name = f"{event_id}.mp4"
        cut = work / name
        completed = runner(
            trim_command(recording, cut, start_s=start_s, duration_s=duration_s),
            check=False,
            capture_output=True,
            text=True,
        )
        if completed.returncode != 0 or not cut.is_file():
            raise PortablePackageError("a window could not be cut from its recording")
        destination = out_directory / name
        if blur:
            try:
                blur_until_clean(
                    cut,
                    destination,
                    probe_path=probe_path,
                    work=work / "frames",
                    fps=fps,
                    passes=passes,
                    runner=runner,
                )
            except PlateBlurError as error:
                raise PortablePackageError(f"a window could not be blurred: {error}") from error
        else:
            cut.replace(destination)
        cut.unlink(missing_ok=True)
        built.append(PortableSource(event_id=event_id, file_name=name, start_s=0.0))
    return tuple(built)


# What a portable package needs beside its clips, in the order they are copied.
CARRIED_FILES: tuple[str, ...] = (
    "local-video-catalog.json",
    "gemini-video-analysis.json",
    "gemini-window-ranking.json",
    "analysis-look.json",
    "place-names.json",
)


def build_package(
    package_directory: Path,
    out_directory: Path,
    *,
    probe_path: Path,
    blur: bool = True,
    fps: float = 20.0,
    passes: int = 3,
    music_directory: Path = Path("private-media/music"),
    music_track_id: str | None = "rising-tide",
    runner: Callable[..., subprocess.CompletedProcess[str]] = subprocess.run,
) -> tuple[PortableSource, ...]:
    """Write a package someone else can cut, from one that has been cut here.

    The windows are the ones the finished plan uses. Each becomes a clip; the
    record is narrowed to those windows so the package says only what it
    carries; the track is copied in and the manifest rewritten to point at it,
    because a manifest naming a drive is a manifest that names this machine.
    """
    import shutil

    from app.local_pipeline import LocalPipelineInputs, load_local_pipeline_inputs

    plan_path = package_directory / "journey-story-plan.json"
    record_path = package_directory / "gemini-video-analysis.json"
    if not plan_path.is_file() or not record_path.is_file():
        raise PortablePackageError("a portable package is built from a package already cut")
    plan = json.loads(plan_path.read_text(encoding="utf-8"))
    wanted = [beat["event_id"] for beat in plan.get("beats", ()) if beat.get("event_id")]
    if not wanted:
        raise PortablePackageError("the finished plan names no footage")

    inputs = load_local_pipeline_inputs(package_directory / "local-pipeline-inputs.json")
    record = json.loads(record_path.read_text(encoding="utf-8"))
    analysed = {item["event_id"]: item for item in record["analysed"]}
    catalog = json.loads((package_directory / "local-video-catalog.json").read_text("utf-8"))
    file_names = {entry["asset_id"]: entry["file_name"] for entry in catalog["entries"]}

    windows: list[tuple[str, Path, float, float]] = []
    for event_id in dict.fromkeys(wanted):
        item = analysed.get(event_id)
        if item is None:
            raise PortablePackageError("the plan names a window the record does not")
        file_name = file_names.get(item["asset_id"])
        if file_name is None:
            raise PortablePackageError("a window names an asset the catalog lacks")
        found = [
            path
            for path in Path(inputs.video_root).rglob(file_name)
            if path.is_file() and not path.is_symlink()
        ]
        if not found:
            raise PortablePackageError("a window names a recording that is no longer there")
        start = float(item["start_offset_s"])
        windows.append((event_id, found[0], start, float(item["end_offset_s"]) - start))

    out_directory.mkdir(parents=True, exist_ok=True)
    work = out_directory / ".building"
    try:
        built = build_portable_sources(
            windows,
            out_directory / FILM_SOURCES_DIRECTORY_NAME,
            probe_path=probe_path,
            work=work,
            blur=blur,
            fps=fps,
            passes=passes,
            runner=runner,
        )
    finally:
        shutil.rmtree(work, ignore_errors=True)

    shipped = {source.event_id for source in built}
    record["analysed"] = [item for item in record["analysed"] if item["event_id"] in shipped]
    for name in CARRIED_FILES:
        source = package_directory / name
        if not source.is_file():
            continue
        if name == "gemini-video-analysis.json":
            (out_directory / name).write_text(
                json.dumps(record, ensure_ascii=False, indent=2), encoding="utf-8"
            )
        else:
            shutil.copy2(source, out_directory / name)
    track = out_directory / Path(inputs.gpx_path).name
    shutil.copy2(inputs.gpx_path, track)
    portable_inputs = LocalPipelineInputs(
        gpx_path=track.resolve(),
        video_root=(out_directory / FILM_SOURCES_DIRECTORY_NAME).resolve(),
        video_to_gps_offset_s=inputs.video_to_gps_offset_s,
        target_duration_s=inputs.target_duration_s,
        output_language=inputs.output_language,
    )
    (out_directory / "local-pipeline-inputs.json").write_text(
        json.dumps(portable_inputs.to_dict(), ensure_ascii=False, indent=2), encoding="utf-8"
    )
    copy_music(out_directory, music_directory=music_directory, track_id=music_track_id)
    write_film_sources(out_directory / FILM_SOURCES_FILE_NAME, built)
    return built


def copy_music(
    out_directory: Path,
    *,
    music_directory: Path = Path("private-media/music"),
    track_id: str | None = None,
) -> None:
    """Carry the one track the package is scored with, and its attribution.

    The tracks are Creative Commons By Attribution 4.0, so they may travel
    with the package as long as the credit does. The catalogue is narrowed to
    what is carried, because a catalogue naming four tracks that are not there
    is a catalogue that lies.
    """
    import shutil

    catalogue = music_directory / "music-catalogue.json"
    if track_id is None or not catalogue.is_file():
        return
    payload = json.loads(catalogue.read_text(encoding="utf-8"))
    tracks = [track for track in payload.get("tracks", ()) if track.get("track_id") == track_id]
    if not tracks:
        raise PortablePackageError("the package is scored with a track the catalogue lacks")
    source = music_directory / str(tracks[0]["file_name"])
    if not source.is_file():
        raise PortablePackageError("the track the package is scored with is not there")
    music = out_directory / "music"
    music.mkdir(parents=True, exist_ok=True)
    shutil.copy2(source, music / source.name)
    payload["tracks"] = tracks
    payload["track_count"] = 1
    (music / "music-catalogue.json").write_text(
        json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8"
    )


@dataclass(frozen=True)
class Hardening:
    """What a pass over a package's clips found and did."""

    dropped: tuple[str, ...] = ()
    blurred: tuple[str, ...] = ()
    clean: tuple[str, ...] = ()

    @property
    def settled(self) -> bool:
        return not self.dropped and not self.blurred


def harden_package(
    package_directory: Path,
    *,
    probe_path: Path,
    work: Path,
    fps: float = 10.0,
    passes: int = 3,
    rounds: int = 4,
    runner: Callable[..., subprocess.CompletedProcess[str]] = subprocess.run,
) -> Hardening:
    """Look at every clip, drop the ones with a face, blur the rest again.

    Encoding a clip changes its pixels, and a reader that missed a plate in
    one encode reads it in the next, so a package is not finished when it is
    built: it is finished when a pass over it finds nothing. A clip with a
    face is not blurred but removed, which is the owner's rule, and the map
    and the judgement are narrowed with it so the package still says only
    what it carries.
    """
    from app.plate_blur import inspect_footage

    if rounds < 1:
        raise PortablePackageError("there must be at least one round")
    clips = package_directory / FILM_SOURCES_DIRECTORY_NAME
    dropped: list[str] = []
    blurred: list[str] = []
    clean: list[str] = []
    for _ in range(rounds):
        changed = False
        clean = []
        sources = load_film_sources(package_directory / FILM_SOURCES_FILE_NAME)
        for source in sources:
            clip = clips / source.file_name
            if not clip.is_file():
                continue
            regions, faces = inspect_footage(
                clip, probe_path=probe_path, work=work, fps=fps, runner=runner
            )
            if faces:
                clip.unlink()
                dropped.append(source.event_id)
                changed = True
                continue
            if regions:
                blur_until_clean(
                    clip,
                    clip,
                    probe_path=probe_path,
                    work=work,
                    fps=fps,
                    passes=passes,
                    runner=runner,
                )
                blurred.append(source.event_id)
                changed = True
                continue
            clean.append(source.event_id)
        _narrow_to_clips(package_directory)
        if not changed:
            break
    return Hardening(
        dropped=tuple(dict.fromkeys(dropped)),
        blurred=tuple(dict.fromkeys(blurred)),
        clean=tuple(clean),
    )


def harden_from_film(
    package_directory: Path,
    film: Path,
    *,
    probe_path: Path,
    work: Path,
    fps: float = 30.0,
    runner: Callable[..., subprocess.CompletedProcess[str]] = subprocess.run,
) -> tuple[str, ...]:
    """Blur, in the clips, what the finished film turns out to show.

    A clip and the film cut from it are different encodes, and a plate the
    reader cannot make out in one it reads in the other: clips clean at every
    frame still produced a legible plate once cut. So the film is read, each
    region is traced back through the plan to the clip it came from, and that
    clip is blurred there for its whole length -- over-blurring in time,
    because the exact seconds inside the clip are not worth deriving and a
    small soft patch throughout is no worse to watch.

    Returns the clips changed. Cut the film again afterwards.
    """
    from app.plate_blur import Region, blur_plates, inspect_footage

    plan_path = package_directory / "journey-story-plan.json"
    if not plan_path.is_file():
        raise PortablePackageError("the film has no plan to trace its regions through")
    regions, _ = inspect_footage(film, probe_path=probe_path, work=work, fps=fps, runner=runner)
    if not regions:
        return ()
    plan = json.loads(plan_path.read_text(encoding="utf-8"))
    at = 0.0
    spans: list[tuple[float, float, str | None]] = []
    for beat in plan.get("beats", ()):
        spans.append((at, at + float(beat["screen_duration_s"]), beat.get("event_id")))
        at += float(beat["screen_duration_s"])
    sources = {
        source.event_id: source
        for source in load_film_sources(package_directory / FILM_SOURCES_FILE_NAME)
    }
    clips = package_directory / FILM_SOURCES_DIRECTORY_NAME
    wanted: dict[str, list[Region]] = {}
    for region in regions:
        middle = (region.start_s + region.end_s) / 2
        event = next((event for a, b, event in spans if a <= middle < b), None)
        if event is None or event not in sources:
            continue
        wanted.setdefault(event, []).append(region)
    changed: list[str] = []
    for event, found in wanted.items():
        clip = clips / sources[event].file_name
        if not clip.is_file():
            continue
        length = _clip_seconds(clip, runner=runner)
        whole = [
            Region(
                start_s=0.0,
                end_s=length,
                x=region.x,
                y=region.y,
                width=region.width,
                height=region.height,
            )
            for region in found
        ]
        blur_plates(clip, clip, whole, runner=runner)
        changed.append(event)
    return tuple(changed)


def _clip_seconds(
    clip: Path, *, runner: Callable[..., subprocess.CompletedProcess[str]] = subprocess.run
) -> float:
    command = (
        "ffprobe", "-v", "error", "-show_entries", "format=duration",
        "-of", "default=nw=1:nk=1", str(clip),
    )  # fmt: skip
    completed = runner(command, check=False, capture_output=True, text=True)
    try:
        return max(0.1, float(completed.stdout.strip().splitlines()[0]))
    except (IndexError, ValueError) as error:
        raise PortablePackageError("a clip's length could not be read") from error


def _narrow_to_clips(package_directory: Path) -> None:
    """Keep the map and the judgement to the clips that are still there."""
    clips = package_directory / FILM_SOURCES_DIRECTORY_NAME
    sources = [
        source
        for source in load_film_sources(package_directory / FILM_SOURCES_FILE_NAME)
        if (clips / source.file_name).is_file()
    ]
    if not sources:
        raise PortablePackageError("every clip was dropped; nothing is left to cut")
    write_film_sources(package_directory / FILM_SOURCES_FILE_NAME, sources)
    kept = {source.event_id for source in sources}
    record_path = package_directory / "gemini-video-analysis.json"
    if record_path.is_file():
        record = json.loads(record_path.read_text(encoding="utf-8"))
        record["analysed"] = [item for item in record["analysed"] if item["event_id"] in kept]
        record_path.write_text(json.dumps(record, ensure_ascii=False, indent=2), encoding="utf-8")


def settle_package(package_directory: Path) -> Path:
    """Point a package's manifest at wherever it now sits.

    The manifest holds absolute paths, and the machine that built the package
    is not the machine that will cut it. This rewrites the two that matter --
    the track and the clips -- to where they actually are, and refuses a
    directory that is not a portable package.
    """
    from app.local_pipeline import load_local_pipeline_inputs

    directory = package_directory.resolve()
    manifest = directory / "local-pipeline-inputs.json"
    if not manifest.is_file():
        raise PortablePackageError("that directory holds no package manifest")
    if not (directory / FILM_SOURCES_FILE_NAME).is_file():
        raise PortablePackageError("that package is not portable; it names recordings")
    tracks = sorted(directory.glob("*.gpx"))
    if not tracks:
        raise PortablePackageError("the package carries no track")
    clips = directory / FILM_SOURCES_DIRECTORY_NAME
    if not clips.is_dir():
        raise PortablePackageError("the package carries no clips")
    payload = json.loads(manifest.read_text(encoding="utf-8"))
    payload["gpx_path"] = str(tracks[0])
    payload["video_root"] = str(clips)
    manifest.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    # Read it back, so a package that cannot be loaded says so now rather than
    # in the middle of a render.
    load_local_pipeline_inputs(manifest)
    return manifest


def main(argv: list[str] | None = None) -> int:
    """Build a portable package from one that has already been cut here."""
    import argparse

    parser = argparse.ArgumentParser(
        prog="python -m app.portable_package",
        description=(
            "Write a package someone else can cut into a film: one blurred clip per "
            "window the finished plan uses, the judgement narrowed to those windows, "
            "and the track. Publishes nothing."
        ),
    )
    parser.add_argument("package", type=Path)
    parser.add_argument(
        "output",
        type=Path,
        nargs="?",
        help="where to write the portable package; omit it with --install",
    )
    parser.add_argument(
        "--install",
        action="store_true",
        help="point an already-built package's manifest at wherever it now sits",
    )
    parser.add_argument(
        "--harden",
        action="store_true",
        help="look at every clip again: drop the ones with a face, blur the rest",
    )
    parser.add_argument(
        "--harden-from-film",
        type=Path,
        default=None,
        help="read a finished film and blur, in the clips, whatever it turns out to show",
    )
    parser.add_argument("--fps", type=float, default=20.0)
    parser.add_argument("--passes", type=int, default=3)
    parser.add_argument(
        "--no-blur", action="store_true", help="skip the plate blur; for a dry run only"
    )
    parser.add_argument("--probe", type=Path, default=Path("private-media/cache/vision-boxes"))
    parser.add_argument("--music", dest="music_track_id", default="rising-tide")
    parser.add_argument("--music-directory", type=Path, default=Path("private-media/music"))
    args = parser.parse_args(argv)
    if args.install:
        try:
            manifest = settle_package(args.package)
        except (PortablePackageError, ValueError) as error:
            print(f"portable package failed: {error}", file=sys.stderr)
            return 1
        print(f"{manifest}: ready to cut")
        return 0
    if args.harden_from_film is not None:
        from tempfile import mkdtemp

        work = Path(mkdtemp(prefix=".hardening-", dir=args.package))
        try:
            changed = harden_from_film(
                args.package, args.harden_from_film, probe_path=args.probe, work=work, fps=args.fps
            )
        except (PortablePackageError, ValueError) as error:
            print(f"portable package failed: {error}", file=sys.stderr)
            return 1
        finally:
            import shutil as _shutil

            _shutil.rmtree(work, ignore_errors=True)
        print(f"{args.package}: {len(changed)} clips blurred from the film; cut it again")
        return 0
    if args.harden:
        from tempfile import mkdtemp

        work = Path(mkdtemp(prefix=".hardening-", dir=args.package))
        try:
            result = harden_package(
                args.package,
                probe_path=args.probe,
                work=work,
                fps=args.fps,
                passes=args.passes,
            )
        except (PortablePackageError, ValueError) as error:
            print(f"portable package failed: {error}", file=sys.stderr)
            return 1
        finally:
            import shutil as _shutil

            _shutil.rmtree(work, ignore_errors=True)
        print(
            f"{args.package}: {len(result.clean)} clean, {len(result.blurred)} blurred, "
            f"{len(result.dropped)} dropped for a face"
        )
        return 0
    if args.output is None:
        print("portable package failed: an output directory is required", file=sys.stderr)
        return 1
    try:
        built = build_package(
            args.package,
            args.output,
            probe_path=args.probe,
            blur=not args.no_blur,
            fps=args.fps,
            passes=args.passes,
            music_directory=args.music_directory,
            music_track_id=args.music_track_id,
        )
    except (PortablePackageError, ValueError) as error:
        print(f"portable package failed: {error}", file=sys.stderr)
        return 1
    print(f"{args.output}: {len(built)} clips")
    return 0


__all__ = [
    "CARRIED_FILES",
    "build_package",
    "Hardening",
    "copy_music",
    "harden_from_film",
    "harden_package",
    "settle_package",
    "main",
    "CLIP_HEIGHT",
    "FILM_SOURCES_DIRECTORY_NAME",
    "FILM_SOURCES_FILE_NAME",
    "FILM_SOURCES_SCHEMA_VERSION",
    "PortablePackageError",
    "PortableSource",
    "build_portable_sources",
    "film_sources_or_none",
    "load_film_sources",
    "trim_command",
    "write_film_sources",
]


if __name__ == "__main__":
    raise SystemExit(main())
