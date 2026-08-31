import math
import struct

import pytest

from app.video.gpmf_metrics import (
    GpmfMetricSample,
    parse_ffprobe_packet_data,
    parse_gpmf_nodes,
    summarize_gpmf_packet,
    summarize_gpmf_window,
)


def _klv(key: str, type_character: str | None, structure_size: int, payload: bytes) -> bytes:
    if len(payload) % structure_size:
        raise ValueError("payload must contain complete structures")
    repeat = len(payload) // structure_size
    header = key.encode("ascii") + bytes([0 if type_character is None else ord(type_character)])
    header += bytes([structure_size]) + repeat.to_bytes(2, "big")
    padding = b"\0" * ((4 - len(payload) % 4) % 4)
    return header + payload + padding


def _stream(*nodes: bytes) -> bytes:
    payload = b"".join(nodes)
    return _klv("STRM", None, 1, payload)


def _metric_sample(time_s: float, natural: float) -> GpmfMetricSample:
    return GpmfMetricSample(
        time_s=time_s,
        duration_s=1.0,
        gyro_sustained_rad_s=0.2,
        gyro_jitter_rad_s=0.1,
        gyro_peak_rad_s=0.4,
        acceleration_jitter_mps2=1.5,
        iso_mean=100,
        shutter_mean_s=0.001,
        luma_mean=120,
        uniformity_mean=0.2,
        natural_scene_probability=natural,
        built_scene_probability=1 - natural,
        scene_confidence=0.6,
        hue_weight_mean=0.5,
    )


def test_gpmf_parser_and_summary_decode_safe_camera_metrics() -> None:
    gyro = struct.pack(">hhhhhh", 20, 0, 0, 40, 0, 0)
    acceleration = struct.pack(">hhhhhh", 0, 0, 100, 0, 20, 100)
    scenes = b"".join(
        label + struct.pack(">f", probability)
        for label, probability in (
            (b"SNOW", 0.1),
            (b"URBA", 0.2),
            (b"INDO", 0.1),
            (b"WATR", 0.1),
            (b"VEGE", 0.3),
            (b"BEAC", 0.2),
        )
    )
    payload = _klv(
        "DEVC",
        None,
        1,
        _stream(
            _klv("SCAL", "s", 2, struct.pack(">h", 10)),
            _klv("GYRO", "s", 6, gyro),
        )
        + _stream(
            _klv("SCAL", "s", 2, struct.pack(">h", 10)),
            _klv("ACCL", "s", 6, acceleration),
        )
        + _stream(_klv("SCEN", "?", 8, scenes))
        + _stream(_klv("YAVG", "B", 1, bytes([100, 140])))
        + _stream(_klv("UNIF", "f", 4, struct.pack(">ff", 0.2, 0.4)))
        + _stream(_klv("ISOE", "L", 4, struct.pack(">II", 100, 200)))
        + _stream(_klv("SHUT", "f", 4, struct.pack(">ff", 0.001, 0.002)))
        + _stream(_klv("HUES", "?", 2, bytes([10, 100, 20, 200]))),
    )

    sample = summarize_gpmf_packet(
        parse_gpmf_nodes(payload),
        time_s=3.0,
        duration_s=1.0,
    )

    assert sample is not None
    assert sample.gyro_sustained_rad_s == pytest.approx(3.0)
    assert sample.gyro_jitter_rad_s == pytest.approx(1.0)
    assert sample.acceleration_jitter_mps2 == pytest.approx(1.0)
    assert sample.natural_scene_probability == pytest.approx(0.7)
    assert sample.built_scene_probability == pytest.approx(0.3)
    assert sample.scene_confidence == pytest.approx(0.3)
    assert sample.luma_mean == pytest.approx(120)
    assert sample.uniformity_mean == pytest.approx(0.3)
    assert sample.iso_mean == pytest.approx(150)
    assert sample.shutter_mean_s == pytest.approx(0.0015)
    assert sample.hue_weight_mean == pytest.approx(150 / 255)


def test_gpmf_summary_ignores_gps_payload() -> None:
    payload = _klv(
        "DEVC",
        None,
        1,
        _stream(_klv("GYRO", "s", 6, struct.pack(">hhh", 1, 2, 3)))
        + _stream(_klv("GPS5", "l", 20, bytes(range(20)))),
    )

    sample = summarize_gpmf_packet(
        parse_gpmf_nodes(payload),
        time_s=0.0,
        duration_s=1.0,
    )

    assert sample is not None
    assert not hasattr(sample, "latitude")
    assert not hasattr(sample, "longitude")


def test_ffprobe_hex_dump_parser_ignores_ascii_column() -> None:
    dump = """
00000000: 4445 5643 0000 0004  DEVC....
00000008: 5445 5354            TEST
"""

    assert parse_ffprobe_packet_data(dump) == b"DEVC\0\0\0\x04TEST"


def test_window_summary_reports_coverage_and_averages() -> None:
    result = summarize_gpmf_window(
        (_metric_sample(0.0, 0.2), _metric_sample(1.0, 0.8)),
        start_offset_s=0.5,
        duration_s=2.0,
    )

    assert result is not None
    assert result.natural_scene_probability == pytest.approx(0.5)
    assert result.center_gyro_sustained_rad_s == pytest.approx(0.2)
    assert result.coverage_ratio == pytest.approx(0.75)
    assert math.isfinite(result.gyro_jitter_rad_s)


def test_window_summary_rejects_invalid_interval() -> None:
    with pytest.raises(ValueError, match="positive interval"):
        summarize_gpmf_window((), start_offset_s=-1, duration_s=2)
