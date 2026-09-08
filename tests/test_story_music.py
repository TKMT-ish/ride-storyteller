"""Synthetic-fixture tests for choosing, crediting, and mixing the film's music."""

from __future__ import annotations

import json
import subprocess
from dataclasses import replace
from pathlib import Path

import pytest

from app.story_music import (
    MUSIC_CATALOGUE_SCHEMA_VERSION,
    MusicCatalogue,
    MusicTrack,
    StoryMusicError,
    build_music_mix_command,
    build_music_preview_command,
    load_music_catalogue,
    mix_music_into_film,
    render_music_credits,
    write_music_catalogue,
)


def _track(track_id: str = "wholesome", duration_s: float = 363.8) -> MusicTrack:
    return MusicTrack(
        track_id=track_id,
        title="Wholesome",
        artist="Kevin MacLeod",
        source_url="https://incompetech.com/",
        licence="Creative Commons: By Attribution 4.0",
        licence_url="https://creativecommons.org/licenses/by/4.0/",
        file_name="Wholesome.mp3",
        duration_s=duration_s,
    )


def _ok(*_args, **_kwargs) -> subprocess.CompletedProcess[str]:
    return subprocess.CompletedProcess(args=(), returncode=0, stdout="", stderr="")


# --- the record that says we may use it -------------------------------------


def test_a_track_carries_its_own_credit_line() -> None:
    attribution = _track().attribution

    assert "Wholesome" in attribution
    assert "Kevin MacLeod" in attribution
    assert "Creative Commons: By Attribution 4.0" in attribution
    assert "https://creativecommons.org/licenses/by/4.0/" in attribution


def test_a_track_without_its_licence_details_is_refused() -> None:
    for missing in ("title", "artist", "source_url", "licence"):
        with pytest.raises(ValueError, match="needs its"):
            MusicTrack(
                track_id="x",
                title="" if missing == "title" else "Wholesome",
                artist="" if missing == "artist" else "Kevin MacLeod",
                source_url="" if missing == "source_url" else "https://example.test/",
                licence="" if missing == "licence" else "CC BY 4.0",
                licence_url="https://example.test/licence",
                file_name="a.mp3",
                duration_s=10.0,
            )


def test_a_track_file_name_cannot_be_a_path() -> None:
    with pytest.raises(ValueError, match="must not be a path"):
        MusicTrack(
            track_id="x",
            title="t",
            artist="a",
            source_url="https://example.test/",
            licence="CC BY 4.0",
            licence_url="https://example.test/l",
            file_name="../outside.mp3",
            duration_s=10.0,
        )


def test_credits_list_every_track() -> None:
    credits = render_music_credits((_track(), _track("windswept")))

    assert credits.count("Kevin MacLeod") == 2
    assert credits.startswith("# Music credits")


def test_credits_need_a_track() -> None:
    with pytest.raises(StoryMusicError, match="at least one track"):
        render_music_credits(())


def test_a_catalogue_round_trips(tmp_path: Path) -> None:
    catalogue = MusicCatalogue((_track(), _track("windswept", duration_s=208.3)))
    path = tmp_path / "music-catalogue.json"

    write_music_catalogue(path, catalogue)

    assert load_music_catalogue(path) == catalogue
    payload = json.loads(path.read_text(encoding="utf-8"))
    assert payload["schema_version"] == MUSIC_CATALOGUE_SCHEMA_VERSION
    assert payload["track_count"] == 2


def test_a_catalogue_finds_a_track_by_id_and_refuses_an_unknown_one() -> None:
    catalogue = MusicCatalogue((_track(), _track("windswept")))

    assert catalogue.track("windswept").track_id == "windswept"
    with pytest.raises(StoryMusicError, match="no track in the catalogue"):
        catalogue.track("absent")


def test_a_catalogue_must_not_repeat_a_track() -> None:
    with pytest.raises(ValueError, match="must not repeat"):
        MusicCatalogue((_track(), _track()))


def test_a_malformed_or_missing_catalogue_is_refused(tmp_path: Path) -> None:
    with pytest.raises(StoryMusicError, match="unavailable"):
        load_music_catalogue(tmp_path / "absent.json")

    broken = tmp_path / "broken.json"
    broken.write_text("{not json", encoding="utf-8")
    with pytest.raises(StoryMusicError, match="unreadable"):
        load_music_catalogue(broken)

    wrong = tmp_path / "wrong.json"
    wrong.write_text(json.dumps({"schema_version": "v0", "tracks": []}), encoding="utf-8")
    with pytest.raises(StoryMusicError, match="unsupported"):
        load_music_catalogue(wrong)


# --- the mix ----------------------------------------------------------------


def test_a_short_track_is_looped_so_the_film_never_plays_out_silent(tmp_path: Path) -> None:
    command = build_music_mix_command(
        tmp_path / "film.mp4",
        tmp_path / "track.mp3",
        tmp_path / "scored.mp4",
        film_duration_s=300.0,
        track_duration_s=208.0,
    )

    assert "-stream_loop" in command
    assert command[command.index("-stream_loop") + 1] == "-1"


def test_a_long_track_is_trimmed_rather_than_looped(tmp_path: Path) -> None:
    command = build_music_mix_command(
        tmp_path / "film.mp4",
        tmp_path / "track.mp3",
        tmp_path / "scored.mp4",
        film_duration_s=300.0,
        track_duration_s=380.0,
    )

    assert "-stream_loop" not in command
    assert command[command.index("-t") + 1] == "300.000"


def test_the_sound_always_ends_with_the_picture(tmp_path: Path) -> None:
    for track_duration_s in (208.0, 380.0):
        command = build_music_mix_command(
            tmp_path / "film.mp4",
            tmp_path / "track.mp3",
            tmp_path / "scored.mp4",
            film_duration_s=300.0,
            track_duration_s=track_duration_s,
        )
        assert command[command.index("-t") + 1] == "300.000"


def test_music_is_faded_up_and_down(tmp_path: Path) -> None:
    command = build_music_mix_command(
        tmp_path / "film.mp4",
        tmp_path / "track.mp3",
        tmp_path / "scored.mp4",
        film_duration_s=300.0,
        track_duration_s=380.0,
        fade_in_s=2.0,
        fade_out_s=4.0,
    )
    graph = command[command.index("-filter_complex") + 1]

    assert "afade=t=in:st=0:d=2.000" in graph
    assert "afade=t=out:st=296.000:d=4.000" in graph


def test_the_picture_is_copied_not_re_encoded(tmp_path: Path) -> None:
    """The film was already decided; re-encoding it to add sound costs minutes."""
    command = build_music_mix_command(
        tmp_path / "film.mp4",
        tmp_path / "track.mp3",
        tmp_path / "scored.mp4",
        film_duration_s=300.0,
        track_duration_s=380.0,
    )

    assert command[command.index("-c:v") + 1] == "copy"
    assert command[command.index("-c:a") + 1] == "aac"
    assert "0:v:0" in command


def test_fades_that_do_not_fit_are_refused(tmp_path: Path) -> None:
    with pytest.raises(StoryMusicError, match="do not fit"):
        build_music_mix_command(
            tmp_path / "film.mp4",
            tmp_path / "track.mp3",
            tmp_path / "scored.mp4",
            film_duration_s=3.0,
            track_duration_s=380.0,
            fade_in_s=2.0,
            fade_out_s=4.0,
        )


def test_impossible_durations_are_refused(tmp_path: Path) -> None:
    with pytest.raises(StoryMusicError, match="real durations"):
        build_music_mix_command(
            tmp_path / "film.mp4",
            tmp_path / "track.mp3",
            tmp_path / "scored.mp4",
            film_duration_s=0.0,
            track_duration_s=380.0,
        )
    with pytest.raises(StoryMusicError, match="negative time"):
        build_music_mix_command(
            tmp_path / "film.mp4",
            tmp_path / "track.mp3",
            tmp_path / "scored.mp4",
            film_duration_s=300.0,
            track_duration_s=380.0,
            fade_in_s=-1.0,
        )


# --- running the mix --------------------------------------------------------


def test_a_successful_mix_returns_the_scored_film(tmp_path: Path) -> None:
    (tmp_path / "Wholesome.mp3").write_bytes(b"audio")
    output = tmp_path / "scored.mp4"

    def runner(command, **_kwargs) -> subprocess.CompletedProcess[str]:
        Path(command[-1]).write_bytes(b"scored")
        return _ok()

    result = mix_music_into_film(
        tmp_path / "film.mp4", _track(), tmp_path, output, film_duration_s=300.0, runner=runner
    )

    assert result == output
    assert output.is_file()


def test_an_interrupted_mix_leaves_no_scored_film(tmp_path: Path) -> None:
    (tmp_path / "Wholesome.mp3").write_bytes(b"audio")
    output = tmp_path / "scored.mp4"

    def dying(command, **_kwargs) -> subprocess.CompletedProcess[str]:
        Path(command[-1]).write_bytes(b"half a film")
        raise subprocess.TimeoutExpired(cmd="ffmpeg", timeout=1.0)

    with pytest.raises(StoryMusicError, match="timed out"):
        mix_music_into_film(
            tmp_path / "film.mp4",
            _track(),
            tmp_path,
            output,
            film_duration_s=300.0,
            runner=dying,
        )

    assert not output.exists()


def test_a_missing_track_file_stops_the_mix(tmp_path: Path) -> None:
    with pytest.raises(StoryMusicError, match="track's file is unavailable"):
        mix_music_into_film(
            tmp_path / "film.mp4",
            _track(),
            tmp_path,
            tmp_path / "scored.mp4",
            film_duration_s=300.0,
            runner=_ok,
        )


def test_a_mix_that_produces_no_file_is_reported(tmp_path: Path) -> None:
    (tmp_path / "Wholesome.mp3").write_bytes(b"audio")

    with pytest.raises(StoryMusicError, match="did not create"):
        mix_music_into_film(
            tmp_path / "film.mp4",
            _track(),
            tmp_path,
            tmp_path / "scored.mp4",
            film_duration_s=300.0,
            runner=_ok,
        )


def test_an_existing_scored_film_is_not_replaced_by_accident(tmp_path: Path) -> None:
    (tmp_path / "Wholesome.mp3").write_bytes(b"audio")
    output = tmp_path / "scored.mp4"
    output.write_bytes(b"earlier")

    with pytest.raises(FileExistsError):
        mix_music_into_film(
            tmp_path / "film.mp4",
            _track(),
            tmp_path,
            output,
            film_duration_s=300.0,
            runner=_ok,
        )


# --- previews ---------------------------------------------------------------


def test_a_preview_takes_a_short_listen_from_inside_the_film(tmp_path: Path) -> None:
    command = build_music_preview_command(
        tmp_path / "film.mp4",
        tmp_path / "track.mp3",
        tmp_path / "preview.mp4",
        start_s=30.0,
        duration_s=25.0,
        track_duration_s=380.0,
    )

    assert command.count("-ss") == 2
    assert command[command.index("-t") + 1] == "25.000"
    assert command[command.index("-c:v") + 1] == "copy"


def test_a_preview_of_a_short_track_still_has_sound_throughout(tmp_path: Path) -> None:
    command = build_music_preview_command(
        tmp_path / "film.mp4",
        tmp_path / "track.mp3",
        tmp_path / "preview.mp4",
        start_s=200.0,
        duration_s=25.0,
        track_duration_s=208.0,
    )

    assert "-stream_loop" in command


def test_an_impossible_preview_is_refused(tmp_path: Path) -> None:
    with pytest.raises(StoryMusicError, match="positive duration"):
        build_music_preview_command(
            tmp_path / "film.mp4",
            tmp_path / "track.mp3",
            tmp_path / "preview.mp4",
            start_s=0.0,
            duration_s=0.0,
            track_duration_s=380.0,
        )


def test_a_track_can_carry_the_extra_credit_its_library_asks_for() -> None:
    """Some libraries ask for a line beyond the licence's own: naming who
    promoted the track. The credit the film prints must be the one asked for."""
    plain = MusicTrack(
        track_id="t",
        title="Wandering",
        artist="Numall Fix",
        source_url="https://example.test/artist",
        licence="Creative Commons: By Attribution 3.0 Unported",
        licence_url="https://creativecommons.org/licenses/by/3.0/",
        file_name="Wandering.mp3",
        duration_s=354.3,
    )
    asked = replace(plain, also_credit="royalty free music by https://example.test/library")

    assert plain.attribution.endswith("https://creativecommons.org/licenses/by/3.0/")
    assert asked.attribution.endswith("royalty free music by https://example.test/library")
    assert asked.attribution.startswith("Wandering by Numall Fix")
