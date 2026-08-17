import re
from dataclasses import dataclass
from pathlib import Path

_TIMING = re.compile(
    r"^(\d{2}):(\d{2}):(\d{2}),(\d{3}) --> "
    r"(\d{2}):(\d{2}):(\d{2}),(\d{3})$"
)


@dataclass(frozen=True)
class Cue:
    number: int
    start_ms: int
    end_ms: int
    text: str


def _milliseconds(values: tuple[str, str, str, str]) -> int:
    hours, minutes, seconds, milliseconds = map(int, values)
    return (((hours * 60) + minutes) * 60 + seconds) * 1_000 + milliseconds


def _load_cues() -> tuple[Cue, ...]:
    contents = Path("docs/submission/demo-subtitles-en.srt").read_text(encoding="utf-8")
    cues: list[Cue] = []
    for block in contents.strip().split("\n\n"):
        lines = block.splitlines()
        assert len(lines) >= 3
        timing = _TIMING.fullmatch(lines[1])
        assert timing is not None
        cues.append(
            Cue(
                number=int(lines[0]),
                start_ms=_milliseconds(timing.groups()[:4]),
                end_ms=_milliseconds(timing.groups()[4:]),
                text=" ".join(lines[2:]),
            )
        )
    return tuple(cues)


def test_submission_subtitles_cover_three_minutes_without_overlap() -> None:
    cues = _load_cues()

    assert [cue.number for cue in cues] == list(range(1, len(cues) + 1))
    assert cues[0].start_ms == 0
    assert cues[-1].end_ms == 180_000
    for previous, current in zip(cues, cues[1:], strict=False):
        assert previous.end_ms <= current.start_ms
    for cue in cues:
        assert 0 < cue.end_ms - cue.start_ms <= 13_000
        assert cue.text.strip()


def test_submission_subtitles_keep_unverified_real_media_explicitly_gated() -> None:
    text = "\n".join(cue.text for cue in _load_cues())

    assert "REAL MEDIA GATE" in text
    assert "not available in this draft" in text
    assert "approved clip analysis" in text
    assert "/Users/" not in text
    assert "gs://" not in text
    assert "AIza" not in text
    assert all(ord(character) < 128 for character in text)
