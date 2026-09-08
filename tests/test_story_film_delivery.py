"""The film is encoded to be delivered, not archived (E-8).

CRF 20 with no ceiling produced 32 Mbps on a day of motorcycle footage:
1.3 GB for five minutes. A subscriber on a phone streams none of that. The
command must carry a quality target the encoder can hold and a ceiling on
the busiest stretch, and the header must sit at the front so playback
starts before the download ends.
"""

from __future__ import annotations

from pathlib import Path

from app.story_film import (
    STORY_FILM_BUFFER_KBITS,
    STORY_FILM_CRF,
    STORY_FILM_MAX_BITRATE_KBPS,
    StoryFilmSegment,
    build_story_film_command,
)
from app.story_timeline import StoryBeatKind


def _command(tmp_path: Path) -> list[str]:
    segment = StoryFilmSegment(StoryBeatKind.FOOTAGE, tmp_path / "clip.mp4", 5.0)
    return list(build_story_film_command((segment,), tmp_path / "out.mp4", overwrite=True))


def test_the_film_is_encoded_with_a_quality_target_and_a_ceiling(tmp_path: Path) -> None:
    command = _command(tmp_path)

    assert command[command.index("-crf") + 1] == str(STORY_FILM_CRF)
    assert command[command.index("-maxrate") + 1] == f"{STORY_FILM_MAX_BITRATE_KBPS}k"
    assert command[command.index("-bufsize") + 1] == f"{STORY_FILM_BUFFER_KBITS}k"


def test_the_ceiling_fits_a_phone_on_mobile_data() -> None:
    assert 6_000 <= STORY_FILM_MAX_BITRATE_KBPS <= 12_000, "8-12 Mbps is the delivery band"
    assert STORY_FILM_BUFFER_KBITS >= STORY_FILM_MAX_BITRATE_KBPS, "VBV needs at least a second"
    assert 21 <= STORY_FILM_CRF <= 26, "still good, not archival"


def test_the_header_sits_at_the_front_for_streaming(tmp_path: Path) -> None:
    command = _command(tmp_path)

    assert command[command.index("-movflags") + 1] == "+faststart"
    assert "-an" in command, "music is mixed in afterwards; the cut itself is silent"
