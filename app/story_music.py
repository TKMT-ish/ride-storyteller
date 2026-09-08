"""Choose the film's music, and keep the record that says we may use it.

Gate 3 of docs/completion-roadmap-ja.md. The film is cut silent: the footage's
own engine and wind noise is dropped and no narration is added, so music is
the only sound it will have. That makes the licence part of the deliverable,
not an afterthought. Every track here carries its title, composer, source,
licence, and the exact credit line its licence asks for, and that record is
written out separately so a submission can show it without anyone having to
remember where a file came from.

Two facts about real tracks shape the mix. A track is rarely the length of a
film, so one shorter than the film is looped and one longer is trimmed --
either way the sound ends when the picture does. And a track that simply
stops is worse than no music, so it is faded up at the start and down at the
end. The video stream is copied rather than re-encoded: the picture was
already decided, and re-encoding it to add sound would cost minutes and lose
quality for nothing.

Nothing here reaches the network. Tracks are files already on the machine;
this module reads their metadata and builds commands.
"""

from __future__ import annotations

import json
import os
import subprocess
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

MUSIC_CATALOGUE_SCHEMA_VERSION = "story-music-catalogue-v1"

MUSIC_CATALOGUE_FILE_NAME = "music-catalogue.json"

DEFAULT_FADE_IN_S = 2.0
DEFAULT_FADE_OUT_S = 4.0
DEFAULT_MUSIC_BITRATE = "192k"


class StoryMusicError(ValueError):
    """Raised when music cannot be chosen or mixed safely."""


@dataclass(frozen=True)
class MusicTrack:
    """One track, with everything needed to use it and to credit it."""

    track_id: str
    title: str
    artist: str
    source_url: str
    licence: str
    licence_url: str
    file_name: str
    duration_s: float
    # Some libraries ask for a line beyond what the licence itself requires --
    # naming who promoted the track, say. It is carried here so the credit the
    # film prints is the credit that was asked for.
    also_credit: str = ""

    def __post_init__(self) -> None:
        for field_name in ("track_id", "title", "artist", "source_url", "licence", "file_name"):
            if not getattr(self, field_name):
                raise ValueError(f"a music track needs its {field_name.replace('_', ' ')}")
        if self.duration_s <= 0:
            raise ValueError("a music track needs a positive duration")
        if Path(self.file_name).name != self.file_name:
            raise ValueError("a music track's file name must not be a path")

    @property
    def attribution(self) -> str:
        """The credit line this track's licence asks for, spelled out."""
        credit = (
            f"{self.title} by {self.artist} ({self.source_url}) — "
            f"licensed under {self.licence}: {self.licence_url}"
        )
        return f"{credit} — {self.also_credit}" if self.also_credit else credit

    def to_dict(self) -> dict[str, object]:
        return {
            "track_id": self.track_id,
            "title": self.title,
            "artist": self.artist,
            "source_url": self.source_url,
            "licence": self.licence,
            "licence_url": self.licence_url,
            "file_name": self.file_name,
            "duration_s": round(self.duration_s, 3),
            "attribution": self.attribution,
        }


@dataclass(frozen=True)
class MusicCatalogue:
    """Every track available to this film, each usable and each credited."""

    tracks: tuple[MusicTrack, ...]

    def __post_init__(self) -> None:
        if not self.tracks:
            raise ValueError("a music catalogue needs at least one track")
        ids = [track.track_id for track in self.tracks]
        if len(ids) != len(set(ids)):
            raise ValueError("a music catalogue must not repeat a track ID")

    def track(self, track_id: str) -> MusicTrack:
        for candidate in self.tracks:
            if candidate.track_id == track_id:
                return candidate
        raise StoryMusicError("no track in the catalogue has that ID")

    def to_dict(self) -> dict[str, object]:
        return {
            "schema_version": MUSIC_CATALOGUE_SCHEMA_VERSION,
            "track_count": len(self.tracks),
            "tracks": [track.to_dict() for track in self.tracks],
        }


def load_music_catalogue(path: Path) -> MusicCatalogue:
    """Read a catalogue, refusing anything this version cannot trust."""
    if path.is_symlink() or not path.is_file():
        raise StoryMusicError("the music catalogue is unavailable")
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise StoryMusicError("the music catalogue is unreadable") from error
    if not isinstance(payload, dict):
        raise StoryMusicError("the music catalogue is malformed")
    if payload.get("schema_version") != MUSIC_CATALOGUE_SCHEMA_VERSION:
        raise StoryMusicError("unsupported music catalogue schema")
    try:
        return MusicCatalogue(
            tuple(
                MusicTrack(
                    track_id=str(item["track_id"]),
                    title=str(item["title"]),
                    artist=str(item["artist"]),
                    source_url=str(item["source_url"]),
                    licence=str(item["licence"]),
                    licence_url=str(item["licence_url"]),
                    file_name=str(item["file_name"]),
                    duration_s=float(item["duration_s"]),
                    also_credit=str(item.get("also_credit", "")),
                )
                for item in payload["tracks"]
            )
        )
    except (KeyError, TypeError, ValueError) as error:
        raise StoryMusicError("the music catalogue is malformed") from error


def write_music_catalogue(
    output_path: Path, catalogue: MusicCatalogue, *, overwrite: bool = True
) -> Path:
    if output_path.is_symlink():
        raise StoryMusicError("the music catalogue path is unsafe")
    if output_path.exists() and not overwrite:
        raise FileExistsError("a music catalogue already exists at that path")
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(
        json.dumps(catalogue.to_dict(), ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    return output_path


def render_music_credits(tracks: tuple[MusicTrack, ...]) -> str:
    """Write the credits a submission has to show, one line per track."""
    if not tracks:
        raise StoryMusicError("credits need at least one track")
    lines = ["# Music credits", ""]
    lines.extend(f"- {track.attribution}" for track in tracks)
    lines.append("")
    return "\n".join(lines)


def build_music_mix_command(
    film_path: Path,
    track_path: Path,
    output_path: Path,
    *,
    film_duration_s: float,
    track_duration_s: float,
    fade_in_s: float = DEFAULT_FADE_IN_S,
    fade_out_s: float = DEFAULT_FADE_OUT_S,
    bitrate: str = DEFAULT_MUSIC_BITRATE,
    overwrite: bool = False,
) -> tuple[str, ...]:
    """Lay one track under the finished picture for exactly its length.

    A track shorter than the film is looped and a longer one is trimmed, so
    the sound always ends with the picture. It is faded up and down, because
    music that begins or stops abruptly is worse than silence. The video is
    copied untouched: the picture is already decided, and re-encoding it to
    add a soundtrack would cost minutes and quality for nothing.
    """
    if film_duration_s <= 0 or track_duration_s <= 0:
        raise StoryMusicError("a mix needs a film and a track with real durations")
    if fade_in_s < 0 or fade_out_s < 0:
        raise StoryMusicError("a fade cannot last a negative time")
    if fade_in_s + fade_out_s > film_duration_s:
        raise StoryMusicError("the fades do not fit inside the film")

    command: list[str] = [
        "ffmpeg",
        "-hide_banner",
        "-loglevel",
        "error",
        "-y" if overwrite else "-n",
        "-i",
        str(film_path),
    ]
    if track_duration_s < film_duration_s:
        # Loop rather than let the film play out in silence.
        command.extend(("-stream_loop", "-1"))
    command.extend(("-i", str(track_path)))

    fade_out_start = max(0.0, film_duration_s - fade_out_s)
    filters = [
        f"afade=t=in:st=0:d={fade_in_s:.3f}",
        f"afade=t=out:st={fade_out_start:.3f}:d={fade_out_s:.3f}",
    ]
    command.extend(
        (
            "-filter_complex",
            f"[1:a]{','.join(filters)}[a]",
            "-map",
            "0:v:0",
            "-map",
            "[a]",
            "-c:v",
            "copy",
            "-c:a",
            "aac",
            "-b:a",
            bitrate,
            "-t",
            f"{film_duration_s:.3f}",
            "-movflags",
            "+faststart",
            str(output_path),
        )
    )
    return tuple(command)


def mix_music_into_film(
    film_path: Path,
    track: MusicTrack,
    music_directory: Path,
    output_path: Path,
    *,
    film_duration_s: float,
    overwrite: bool = False,
    runner: Callable[..., subprocess.CompletedProcess[str]] = subprocess.run,
) -> Path:
    """Run the mix and confirm the file it was supposed to make exists."""
    track_path = music_directory / track.file_name
    if track_path.is_symlink() or not track_path.is_file():
        raise StoryMusicError("the chosen track's file is unavailable")
    if output_path.is_symlink():
        raise StoryMusicError("the scored film's output path is unsafe")
    if output_path.exists() and not overwrite:
        raise FileExistsError(
            "a scored film already exists; choose a new name or pass overwrite=True"
        )
    # Written beside the destination and moved on only when whole, so an
    # interrupted mix leaves no scored film rather than an unplayable one.
    output_path.parent.mkdir(parents=True, exist_ok=True)
    partial_path = output_path.with_name(
        f".{output_path.stem}.partial-{os.getpid()}{output_path.suffix}"
    )
    partial_path.unlink(missing_ok=True)
    command = build_music_mix_command(
        film_path,
        track_path,
        partial_path,
        film_duration_s=film_duration_s,
        track_duration_s=track.duration_s,
        overwrite=True,
    )
    try:
        completed = runner(
            command,
            check=False,
            capture_output=True,
            text=True,
            timeout=max(300.0, film_duration_s * 5),
        )
    except FileNotFoundError as error:
        partial_path.unlink(missing_ok=True)
        raise StoryMusicError("ffmpeg is required to score the film") from error
    except subprocess.TimeoutExpired as error:
        partial_path.unlink(missing_ok=True)
        raise StoryMusicError("scoring the film timed out") from error
    except BaseException:
        partial_path.unlink(missing_ok=True)
        raise
    if completed.returncode != 0:
        partial_path.unlink(missing_ok=True)
        raise StoryMusicError("ffmpeg could not score the film")
    if not partial_path.is_file():
        raise StoryMusicError("ffmpeg did not create the expected scored film")
    os.replace(partial_path, output_path)
    return output_path


def build_music_preview_command(
    film_path: Path,
    track_path: Path,
    output_path: Path,
    *,
    start_s: float,
    duration_s: float,
    track_duration_s: float,
    overwrite: bool = True,
) -> tuple[str, ...]:
    """Cut a short listen so a person can choose a track by ear, not by name."""
    if duration_s <= 0:
        raise StoryMusicError("a preview needs a positive duration")
    if start_s < 0:
        raise StoryMusicError("a preview cannot start before the film")
    command: list[str] = [
        "ffmpeg",
        "-hide_banner",
        "-loglevel",
        "error",
        "-y" if overwrite else "-n",
        "-ss",
        f"{start_s:.3f}",
        "-i",
        str(film_path),
    ]
    if track_duration_s < start_s + duration_s:
        command.extend(("-stream_loop", "-1"))
    command.extend(
        (
            "-ss",
            f"{start_s:.3f}",
            "-i",
            str(track_path),
            "-filter_complex",
            "[1:a]afade=t=in:st=0:d=1.000,"
            f"afade=t=out:st={max(0.0, duration_s - 1.5):.3f}:d=1.500[a]",
            "-map",
            "0:v:0",
            "-map",
            "[a]",
            "-c:v",
            "copy",
            "-c:a",
            "aac",
            "-b:a",
            DEFAULT_MUSIC_BITRATE,
            "-t",
            f"{duration_s:.3f}",
            "-movflags",
            "+faststart",
            str(output_path),
        )
    )
    return tuple(command)
