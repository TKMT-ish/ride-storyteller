"""Synthetic GPMF tests: the camera's GPS time gives a recording's clock offset."""

from __future__ import annotations

import json
import struct
import subprocess
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from app import gopro_gps
from app.gopro_gps import (
    AGREEMENT_S,
    GOOD_FIX,
    GOOD_PRECISION,
    MIN_FIXES,
    DayClock,
    GoProGpsError,
    GpsFix,
    RecordingClock,
    day_clock,
    parse_gps_fixes,
    recording_clock,
    sidecar_for,
)

_T0 = datetime(2026, 5, 1, 9, 0, 0, tzinfo=UTC)


def _klv(key: bytes, kind: int, size: int, repeat: int, payload: bytes) -> bytes:
    padded = payload + b"\x00" * ((-len(payload)) % 4)
    return key + bytes([kind, size]) + struct.pack(">H", repeat) + padded


def _packet(
    utc: datetime,
    *,
    fix: int = 3,
    precision: int = 150,
    lat: float = -43.5,
    lon: float = 170.2,
    speed: float = 12.0,
) -> bytes:
    """One second of GoPro metadata: a DEVC holding a GPS STRM."""
    gpsu = _klv(b"GPSU", ord("U"), 16, 1, utc.strftime("%y%m%d%H%M%S.%f")[:16].encode())
    gpsf = _klv(b"GPSF", ord("L"), 4, 1, struct.pack(">L", fix))
    gpsp = _klv(b"GPSP", ord("S"), 2, 1, struct.pack(">H", precision))
    scal = _klv(
        b"SCAL", ord("l"), 4, 5, struct.pack(">5l", 10_000_000, 10_000_000, 1000, 1000, 100)
    )
    sample = struct.pack(
        ">5l", int(lat * 1e7), int(lon * 1e7), 100_000, int(speed * 1000), int(speed * 100)
    )
    gps5 = _klv(b"GPS5", ord("l"), 20, 2, sample + sample)
    strm = _klv(b"STRM", 0, 1, 0, gpsu + gpsf + gpsp + scal + gps5)
    strm = (
        strm[:4]
        + bytes([0, 1])
        + struct.pack(">H", len(gpsu + gpsf + gpsp + scal + gps5))
        + strm[8:]
    )
    inner = _klv(b"DVID", ord("L"), 4, 1, struct.pack(">L", 1)) + strm
    return b"DEVC" + bytes([0, 1]) + struct.pack(">H", len(inner)) + inner


def _track(
    seconds: int, camera_start: datetime, true_start: datetime, *, unlocked_first: int = 0
) -> bytes:
    data = b""
    for i in range(seconds):
        if i < unlocked_first:
            data += _packet(datetime(2015, 10, 18, tzinfo=UTC), fix=0, precision=9999)
        else:
            data += _packet(true_start + timedelta(seconds=i))
    return data


def test_each_second_with_a_fix_becomes_one_fix() -> None:
    fixes = parse_gps_fixes(_track(6, _T0, _T0 + timedelta(hours=13), unlocked_first=2))

    assert len(fixes) == 6
    assert [f.is_trusted for f in fixes] == [False, False, True, True, True, True]
    assert fixes[2].utc == _T0 + timedelta(hours=13, seconds=2)
    assert fixes[2].seconds_into_recording == 2
    assert fixes[2].latitude == pytest.approx(-43.5) and fixes[2].speed_mps == pytest.approx(12.0)


def test_the_recordings_clock_is_the_median_gap_between_camera_time_and_gps_time() -> None:
    fixes = parse_gps_fixes(_track(12, _T0, _T0 + timedelta(hours=13), unlocked_first=3))

    clock = recording_clock("GX010001.MP4", _T0, fixes)

    assert clock is not None
    assert clock.offset_s == pytest.approx(13 * 3600.0)
    assert clock.fixes_used == 9 and clock.spread_s == pytest.approx(0.0)


def test_too_few_trusted_seconds_measure_nothing() -> None:
    fixes = parse_gps_fixes(_track(6, _T0, _T0 + timedelta(hours=13), unlocked_first=3))

    assert recording_clock("GX010001.MP4", _T0, fixes) is None


def test_the_day_agrees_when_every_recording_says_the_same_offset(tmp_path: Path) -> None:
    tracks = {
        "GX010001.MP4": _track(20, _T0, _T0 + timedelta(hours=13)),
        "GX010002.MP4": _track(
            20, _T0 + timedelta(minutes=30), _T0 + timedelta(hours=13, minutes=30)
        ),
        "GH010003.MP4": b"",  # a camera whose GPS never locked
    }
    recordings = [
        ("GX010001.MP4", _T0, 20.0),
        ("GX010002.MP4", _T0 + timedelta(minutes=30), 20.0),
        ("GH010003.MP4", _T0 + timedelta(hours=1), 20.0),
    ]
    ride_start = _T0 + timedelta(hours=12)
    ride_end = _T0 + timedelta(hours=20)

    day = day_clock(recordings, tmp_path, ride_start, ride_end, read=lambda p: tracks[p.name])

    assert day.is_unambiguous
    assert day.offset_s == pytest.approx(13 * 3600.0)
    assert day.recordings_measured == 2 and day.recordings_inside == 2
    assert day.recordings_without_gps == 1 and day.recordings_total == 3
    assert day.to_dict()["proposed"]["offset_hours"] == pytest.approx(13.0)


def test_recordings_on_different_clocks_are_not_averaged_quietly(tmp_path: Path) -> None:
    tracks = {
        "GX010001.MP4": _track(20, _T0, _T0 + timedelta(hours=13)),
        "GX010002.MP4": _track(
            20, _T0 + timedelta(minutes=30), _T0 + timedelta(hours=8, minutes=30)
        ),
    }
    recordings = [("GX010001.MP4", _T0, 20.0), ("GX010002.MP4", _T0 + timedelta(minutes=30), 20.0)]

    day = day_clock(
        recordings,
        tmp_path,
        _T0 + timedelta(hours=6),
        _T0 + timedelta(hours=20),
        read=lambda p: tracks[p.name],
    )

    assert not day.is_unambiguous
    assert day.spread_s == pytest.approx(5 * 3600.0)


def test_a_ride_no_recording_falls_into_is_an_error(tmp_path: Path) -> None:
    tracks = {"GX010001.MP4": _track(20, _T0, _T0 + timedelta(hours=13))}
    with pytest.raises(GoProGpsError, match="inside"):
        day_clock(
            [("GX010001.MP4", _T0, 20.0)],
            tmp_path,
            _T0 + timedelta(days=3),
            _T0 + timedelta(days=4),
            read=lambda p: tracks[p.name],
        )


def test_the_low_resolution_proxy_is_read_when_it_exists(tmp_path: Path) -> None:
    recording = tmp_path / "GX011238.MP4"
    recording.write_bytes(b"x")
    assert sidecar_for(recording) == recording
    (tmp_path / "GL011238.LRV").write_bytes(b"x")
    assert sidecar_for(recording) == tmp_path / "GL011238.LRV"


def test_the_command_reports_the_days_clock_as_json(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys
) -> None:
    from app import gopro_gps

    gpx = tmp_path / "ride.gpx"
    start = _T0 + timedelta(hours=12)

    def trkpt(i: int) -> str:
        stamp = (start + timedelta(minutes=i)).strftime("%Y-%m-%dT%H:%M:%SZ")
        return f'<trkpt lat="-43.{i:03d}" lon="170.{i:03d}"><time>{stamp}</time></trkpt>'

    points = "".join(trkpt(i) for i in range(0, 480, 5))
    gpx.write_text(
        '<?xml version="1.0" encoding="UTF-8"?><gpx version="1.1" creator="t" '
        'xmlns="http://www.topografix.com/GPX/1/1"><trk><trkseg>'
        + points
        + "</trkseg></trk></gpx>",
        encoding="utf-8",
    )
    tracks = {"GX010001.MP4": _track(20, _T0, _T0 + timedelta(hours=13))}
    monkeypatch.setattr(gopro_gps, "recordings_in", lambda root: [("GX010001.MP4", _T0, 20.0)])
    monkeypatch.setattr(gopro_gps, "extract_gpmf", lambda p, seconds=None: tracks[p.name])

    gopro_gps.main([str(gpx), str(tmp_path)])

    payload = json.loads(capsys.readouterr().out)
    assert payload["is_unambiguous"] is True
    assert payload["proposed"]["offset_hours"] == pytest.approx(13.0)


# ---------------------------------------------------------------------------
# GpsFix.is_trusted: boundary between a fix worth trusting and one that isn't
# ---------------------------------------------------------------------------


def _fix(seconds: int, utc: datetime, *, fix: int = 3, precision: int = 100) -> GpsFix:
    return GpsFix(
        seconds_into_recording=seconds,
        utc=utc,
        fix=fix,
        precision=precision,
        latitude=-43.5,
        longitude=170.2,
        speed_mps=10.0,
    )


def test_is_trusted_at_exactly_the_good_thresholds() -> None:
    fix = _fix(0, _T0, fix=GOOD_FIX, precision=GOOD_PRECISION)
    assert fix.is_trusted is True


def test_is_trusted_false_one_below_the_good_fix() -> None:
    fix = _fix(0, _T0, fix=GOOD_FIX - 1, precision=GOOD_PRECISION)
    assert fix.is_trusted is False


def test_is_trusted_false_one_worse_than_the_good_precision() -> None:
    fix = _fix(0, _T0, fix=GOOD_FIX, precision=GOOD_PRECISION + 1)
    assert fix.is_trusted is False


# ---------------------------------------------------------------------------
# recording_clock: the MIN_FIXES boundary, built directly from GpsFix (no
# GPMF encoding needed -- this is the pure decision, not the parser)
# ---------------------------------------------------------------------------


def test_recording_clock_at_exactly_min_fixes_measures_something() -> None:
    fixes = [_fix(i, _T0 + timedelta(hours=13, seconds=i)) for i in range(MIN_FIXES)]

    clock = recording_clock("GX010001.MP4", _T0, fixes)

    assert clock is not None
    assert clock.fixes_used == MIN_FIXES
    assert clock.offset_s == pytest.approx(13 * 3600.0)


def test_recording_clock_one_short_of_min_fixes_measures_nothing() -> None:
    fixes = [_fix(i, _T0 + timedelta(hours=13, seconds=i)) for i in range(MIN_FIXES - 1)]

    assert recording_clock("GX010001.MP4", _T0, fixes) is None


def test_recording_clock_ignores_untrusted_fixes_when_counting_min_fixes() -> None:
    """A pile of untrusted fixes must not paper over too few trusted ones."""
    trusted = [_fix(i, _T0 + timedelta(hours=13, seconds=i)) for i in range(MIN_FIXES - 1)]
    untrusted = [_fix(50 + i, _T0, fix=0, precision=9999) for i in range(20)]

    assert recording_clock("GX010001.MP4", _T0, trusted + untrusted) is None


# ---------------------------------------------------------------------------
# RecordingClock.to_dict() / DayClock.to_dict(): rounded, and never name a file
# ---------------------------------------------------------------------------


def test_recording_clock_to_dict_rounds_and_excludes_the_file_name() -> None:
    clock = RecordingClock(
        file_name="GX010001.MP4", offset_s=46807.6789, fixes_used=9, spread_s=0.12345
    )

    payload = clock.to_dict()

    assert payload == {"offset_s": 46807.679, "fixes_used": 9, "spread_s": 0.123}
    assert "file_name" not in payload
    assert "GX010001.MP4" not in json.dumps(payload)


def test_day_clock_to_dict_never_names_a_recording() -> None:
    day = DayClock(
        offset_s=-46808.4321,
        recordings_measured=14,
        recordings_inside=14,
        recordings_total=15,
        recordings_without_gps=1,
        spread_s=2.9,
        is_unambiguous=True,
    )

    payload = day.to_dict()
    serialized = json.dumps(payload)

    assert "GX" not in serialized and "MP4" not in serialized.upper()
    assert payload["proposed"]["offset_s"] == -46808.432
    assert payload["proposed"]["offset_hours"] == round(-46808.4321 / 3600.0, 4)


# ---------------------------------------------------------------------------
# day_clock: the AGREEMENT_S boundary and a reader that fails outright
# ---------------------------------------------------------------------------


def test_day_clock_is_unambiguous_at_exactly_the_agreement_boundary(tmp_path: Path) -> None:
    tracks = {
        "GX010001.MP4": _track(20, _T0, _T0 + timedelta(hours=13)),
        "GX010002.MP4": _track(20, _T0, _T0 + timedelta(hours=13) + timedelta(seconds=AGREEMENT_S)),
    }
    recordings = [("GX010001.MP4", _T0, 20.0), ("GX010002.MP4", _T0, 20.0)]

    day = day_clock(
        recordings,
        tmp_path,
        _T0 + timedelta(hours=12),
        _T0 + timedelta(hours=14),
        read=lambda p: tracks[p.name],
    )

    assert day.spread_s == pytest.approx(AGREEMENT_S)
    assert day.is_unambiguous is True


def test_day_clock_is_ambiguous_just_past_the_agreement_boundary(tmp_path: Path) -> None:
    tracks = {
        "GX010001.MP4": _track(20, _T0, _T0 + timedelta(hours=13)),
        "GX010002.MP4": _track(
            20, _T0, _T0 + timedelta(hours=13) + timedelta(seconds=AGREEMENT_S + 0.5)
        ),
    }
    recordings = [("GX010001.MP4", _T0, 20.0), ("GX010002.MP4", _T0, 20.0)]

    day = day_clock(
        recordings,
        tmp_path,
        _T0 + timedelta(hours=12),
        _T0 + timedelta(hours=14),
        read=lambda p: tracks[p.name],
    )

    assert day.is_unambiguous is False


def test_day_clock_counts_a_recording_whose_reader_fails_as_without_gps(tmp_path: Path) -> None:
    """A recording that cannot be read at all (no gpmd track, corrupt file, ...) must
    fall back to 'without GPS', not blow up the whole day's measurement."""
    good_track = _track(20, _T0, _T0 + timedelta(hours=13))

    def flaky_reader(path: Path) -> bytes:
        if path.name == "GX010002.MP4":
            raise GoProGpsError("the recording has no GoPro metadata track")
        return good_track

    recordings = [
        ("GX010001.MP4", _T0, 20.0),
        ("GX010002.MP4", _T0 + timedelta(minutes=5), 20.0),
    ]

    day = day_clock(
        recordings,
        tmp_path,
        _T0 + timedelta(hours=12),
        _T0 + timedelta(hours=14),
        read=flaky_reader,
    )

    assert day.recordings_without_gps == 1
    assert day.recordings_measured == 1
    assert day.recordings_total == 2
    assert day.is_unambiguous is True


# ---------------------------------------------------------------------------
# sidecar_for: prefix and stem-length boundaries (pure path logic, no I/O
# needed when the prefix check alone already decides the answer)
# ---------------------------------------------------------------------------


def test_sidecar_for_stem_shorter_than_four_chars_is_left_alone() -> None:
    recording = Path("/videos/GX1.MP4")
    assert sidecar_for(recording) == recording


# --- boundary and failure paths (branch cloud/20260906-1035, parser-focused) ------------------


def _strm_klv(payload: bytes) -> bytes:
    """A STRM KLV whose declared size/repeat matches `payload`'s real length."""
    raw = _klv(b"STRM", 0, 1, 0, payload)
    return raw[:4] + bytes([0, 1]) + struct.pack(">H", len(payload)) + raw[8:]


def _devc_klv(inner: bytes) -> bytes:
    return b"DEVC" + bytes([0, 1]) + struct.pack(">H", len(inner)) + inner


def _dvid() -> bytes:
    return _klv(b"DVID", ord("L"), 4, 1, struct.pack(">L", 1))


def _gps5_field(*, lat: float = -43.5, lon: float = 170.2, speed: float = 12.0) -> bytes:
    scal = _klv(
        b"SCAL", ord("l"), 4, 5, struct.pack(">5l", 10_000_000, 10_000_000, 1000, 1000, 100)
    )
    sample = struct.pack(
        ">5l", int(lat * 1e7), int(lon * 1e7), 100_000, int(speed * 1000), int(speed * 100)
    )
    gps5 = _klv(b"GPS5", ord("l"), 20, 2, sample + sample)
    return scal + gps5


def _gpsu_field(raw: bytes) -> bytes:
    return _klv(b"GPSU", ord("U"), 16, 1, raw[:16])


def test_a_devc_with_no_strm_at_all_yields_no_fix() -> None:
    assert parse_gps_fixes(_devc_klv(_dvid())) == ()


def test_a_stream_missing_gps5_yields_no_fix() -> None:
    strm = _strm_klv(_gpsu_field(_T0.strftime("%y%m%d%H%M%S.%f").encode()))
    assert parse_gps_fixes(_devc_klv(_dvid() + strm)) == ()


def test_a_stream_missing_gpsu_yields_no_fix() -> None:
    strm = _strm_klv(_gps5_field())
    assert parse_gps_fixes(_devc_klv(_dvid() + strm)) == ()


def test_a_gpsu_that_does_not_parse_as_a_time_yields_no_fix() -> None:
    strm = _strm_klv(_gpsu_field(b"not-a-timestamp!") + _gps5_field())
    assert parse_gps_fixes(_devc_klv(_dvid() + strm)) == ()


def test_is_trusted_at_the_fix_and_precision_boundary() -> None:
    fixes = parse_gps_fixes(_packet(_T0, fix=GOOD_FIX, precision=GOOD_PRECISION))
    assert fixes[0].is_trusted is True


def test_is_trusted_just_below_the_fix_boundary() -> None:
    fixes = parse_gps_fixes(_packet(_T0, fix=GOOD_FIX - 1, precision=GOOD_PRECISION))
    assert fixes[0].is_trusted is False


def test_is_trusted_just_above_the_precision_boundary() -> None:
    fixes = parse_gps_fixes(_packet(_T0, fix=GOOD_FIX, precision=GOOD_PRECISION + 1))
    assert fixes[0].is_trusted is False


def test_recording_clock_at_exactly_the_minimum_fix_count() -> None:
    fixes = parse_gps_fixes(_track(MIN_FIXES, _T0, _T0 + timedelta(hours=13)))
    assert recording_clock("GX010001.MP4", _T0, fixes) is not None


def test_recording_clock_one_below_the_minimum_fix_count() -> None:
    fixes = parse_gps_fixes(_track(MIN_FIXES - 1, _T0, _T0 + timedelta(hours=13)))
    assert recording_clock("GX010001.MP4", _T0, fixes) is None


def test_sidecar_for_a_stem_shorter_than_four_characters() -> None:
    recording = Path("/videos/GX1.MP4")
    assert sidecar_for(recording) == recording


def test_sidecar_for_non_gopro_prefix_is_left_alone() -> None:
    recording = Path("/videos/IMG1234.MP4")
    assert sidecar_for(recording) == recording


def test_sidecar_for_prefix_match_is_case_sensitive() -> None:
    recording = Path("/videos/gx010001.mp4")
    assert sidecar_for(recording) == recording


def test_sidecar_for_stem_at_the_minimum_length_of_four(tmp_path: Path) -> None:
    recording = tmp_path / "GX01.MP4"
    recording.write_bytes(b"x")
    assert sidecar_for(recording) == recording  # no .LRV sidecar yet

    (tmp_path / "GL01.LRV").write_bytes(b"x")
    assert sidecar_for(recording) == tmp_path / "GL01.LRV"


# ---------------------------------------------------------------------------
# parse_gps_fixes: malformed or incomplete packets are skipped, not raised
# ---------------------------------------------------------------------------


def test_parse_gps_fixes_on_empty_bytes_finds_nothing() -> None:
    assert parse_gps_fixes(b"") == ()


def _strm_packet(payload: bytes) -> bytes:
    """Wrap a STRM payload the way `_packet` does, without requiring GPS5/GPSU."""
    strm = _klv(b"STRM", 0, 1, 0, payload)
    strm = strm[:4] + bytes([0, 1]) + struct.pack(">H", len(payload)) + strm[8:]
    inner = _klv(b"DVID", ord("L"), 4, 1, struct.pack(">L", 1)) + strm
    return b"DEVC" + bytes([0, 1]) + struct.pack(">H", len(inner)) + inner


def test_parse_gps_fixes_skips_a_packet_with_an_unparseable_timestamp() -> None:
    gpsu = _klv(b"GPSU", ord("U"), 16, 1, b"not-a-valid-ts!!")
    gpsf = _klv(b"GPSF", ord("L"), 4, 1, struct.pack(">L", 3))
    gpsp = _klv(b"GPSP", ord("S"), 2, 1, struct.pack(">H", 150))
    scal = _klv(
        b"SCAL", ord("l"), 4, 5, struct.pack(">5l", 10_000_000, 10_000_000, 1000, 1000, 100)
    )
    sample = struct.pack(">5l", int(-43.5 * 1e7), int(170.2 * 1e7), 100_000, 12_000, 1_200)
    gps5 = _klv(b"GPS5", ord("l"), 20, 2, sample + sample)

    fixes = parse_gps_fixes(_strm_packet(gpsu + gpsf + gpsp + scal + gps5))

    assert fixes == ()


def test_parse_gps_fixes_skips_a_packet_missing_gps5() -> None:
    gpsu = _klv(b"GPSU", ord("U"), 16, 1, _T0.strftime("%y%m%d%H%M%S.%f")[:16].encode())
    gpsf = _klv(b"GPSF", ord("L"), 4, 1, struct.pack(">L", 3))
    gpsp = _klv(b"GPSP", ord("S"), 2, 1, struct.pack(">H", 150))

    fixes = parse_gps_fixes(_strm_packet(gpsu + gpsf + gpsp))

    assert fixes == ()


def test_sidecar_for_a_name_that_is_not_a_gopro_prefix() -> None:
    recording = Path("/videos/ABCD0001.MP4")
    assert sidecar_for(recording) == recording


def test_sidecar_for_a_gh_recording_with_a_proxy(tmp_path: Path) -> None:
    recording = tmp_path / "GH011238.MP4"
    recording.write_bytes(b"x")
    (tmp_path / "GL011238.LRV").write_bytes(b"x")
    assert sidecar_for(recording) == tmp_path / "GL011238.LRV"


def test_day_clock_with_no_recordings_at_all_is_an_error(tmp_path: Path) -> None:
    with pytest.raises(GoProGpsError, match="inside"):
        day_clock([], tmp_path, _T0, _T0 + timedelta(hours=1), read=lambda p: b"")


def test_recording_clock_to_dict_rounds_and_omits_the_file_name() -> None:
    clock = RecordingClock(
        file_name="GX010001.MP4", offset_s=46808.12345, fixes_used=9, spread_s=1.23456
    )

    assert clock.to_dict() == {"offset_s": 46808.123, "fixes_used": 9, "spread_s": 1.235}


def test_day_clock_to_dict_reports_an_ambiguous_negative_offset() -> None:
    day = DayClock(
        offset_s=-46808.4,
        recordings_measured=3,
        recordings_inside=2,
        recordings_total=5,
        recordings_without_gps=1,
        spread_s=6.2,
        is_unambiguous=False,
    )

    assert day.to_dict() == {
        "method": "gopro_gps",
        "is_unambiguous": False,
        "proposed": {
            "offset_s": -46808.4,
            "offset_hours": round(-46808.4 / 3600.0, 4),
            "recordings_inside": 2,
            "recordings_total": 5,
            "recordings_measured": 3,
            "recordings_without_gps": 1,
            "spread_s": 6.2,
        },
    }


def test_gpmd_stream_index_finds_the_metadata_stream(monkeypatch: pytest.MonkeyPatch) -> None:
    import json

    def fake_run(cmd, **kwargs):
        streams = [
            {"index": 0, "codec_tag_string": "avc1"},
            {"index": 3, "codec_tag_string": "gpmd"},
        ]
        return subprocess.CompletedProcess(
            cmd, 0, stdout=json.dumps({"streams": streams}), stderr=""
        )

    monkeypatch.setattr(gopro_gps.subprocess, "run", fake_run)

    assert gopro_gps.gpmd_stream_index(Path("x.mp4")) == 3


def test_gpmd_stream_index_is_none_without_a_metadata_track(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import json

    def fake_run(cmd, **kwargs):
        streams = [{"index": 0, "codec_tag_string": "avc1"}]
        return subprocess.CompletedProcess(
            cmd, 0, stdout=json.dumps({"streams": streams}), stderr=""
        )

    monkeypatch.setattr(gopro_gps.subprocess, "run", fake_run)

    assert gopro_gps.gpmd_stream_index(Path("x.mp4")) is None


def test_gpmd_stream_index_raises_when_the_probe_fails(monkeypatch: pytest.MonkeyPatch) -> None:
    def fake_run(cmd, **kwargs):
        return subprocess.CompletedProcess(cmd, 1, stdout="", stderr="no such file")

    monkeypatch.setattr(gopro_gps.subprocess, "run", fake_run)

    with pytest.raises(GoProGpsError, match="probed"):
        gopro_gps.gpmd_stream_index(Path("x.mp4"))


def test_extract_gpmf_raises_without_a_metadata_track(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(gopro_gps, "gpmd_stream_index", lambda p: None)

    with pytest.raises(GoProGpsError, match="no GoPro metadata track"):
        gopro_gps.extract_gpmf(Path("x.mp4"))


def test_extract_gpmf_raises_when_ffmpeg_fails(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(gopro_gps, "gpmd_stream_index", lambda p: 3)

    def fake_run(cmd, **kwargs):
        return subprocess.CompletedProcess(cmd, 1, stdout=b"", stderr=b"boom")

    monkeypatch.setattr(gopro_gps.subprocess, "run", fake_run)

    with pytest.raises(GoProGpsError, match="could not be read"):
        gopro_gps.extract_gpmf(Path("x.mp4"))
