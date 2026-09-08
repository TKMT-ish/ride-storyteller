import dataclasses
import json
import math
import struct
import subprocess
from pathlib import Path

import pytest

from app.video.gpmf_metrics import (
    GpmfMetricError,
    GpmfMetricSample,
    GpmfNode,
    GpmfWindowSummary,
    analyze_gpmf_metrics,
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


def test_window_summary_rejects_zero_duration() -> None:
    with pytest.raises(ValueError, match="positive interval"):
        summarize_gpmf_window((), start_offset_s=0.0, duration_s=0.0)


def test_window_summary_with_no_samples_is_none() -> None:
    assert summarize_gpmf_window((), start_offset_s=0.0, duration_s=1.0) is None


def test_window_summary_excludes_samples_that_only_touch_the_edges() -> None:
    ends_at_window_start = _metric_sample(-1.0, 0.5)
    starts_at_window_end = _metric_sample(1.0, 0.5)

    assert (
        summarize_gpmf_window((ends_at_window_start,), start_offset_s=0.0, duration_s=1.0) is None
    )
    assert (
        summarize_gpmf_window((starts_at_window_end,), start_offset_s=0.0, duration_s=1.0) is None
    )


def test_window_summary_coverage_ratio_is_capped_at_one_for_overlapping_samples() -> None:
    overlapping = (_metric_sample(0.0, 0.5), _metric_sample(0.0, 0.5))

    result = summarize_gpmf_window(overlapping, start_offset_s=0.0, duration_s=1.0)

    assert result is not None
    assert result.coverage_ratio == pytest.approx(1.0)


def test_window_summary_center_sample_breaks_ties_by_input_order() -> None:
    def sample_with_gyro(time_s: float, gyro: float) -> GpmfMetricSample:
        sample = _metric_sample(time_s, 0.5)
        return dataclasses.replace(sample, gyro_sustained_rad_s=gyro)

    first = sample_with_gyro(0.0, 1.0)
    second = sample_with_gyro(1.0, 2.0)

    # Window centered at 1.0 is equidistant from both samples' centers (0.5, 1.5).
    forward = summarize_gpmf_window((first, second), start_offset_s=0.5, duration_s=1.0)
    reversed_order = summarize_gpmf_window((second, first), start_offset_s=0.5, duration_s=1.0)

    assert forward is not None and reversed_order is not None
    assert forward.center_gyro_sustained_rad_s == pytest.approx(1.0)
    assert reversed_order.center_gyro_sustained_rad_s == pytest.approx(2.0)


def test_parse_gpmf_nodes_handles_empty_and_truncated_input() -> None:
    assert parse_gpmf_nodes(b"") == ()
    assert parse_gpmf_nodes(b"ABCD\x00\x01") == ()  # shorter than an 8-byte header


def test_parse_gpmf_nodes_stops_at_a_null_key() -> None:
    assert parse_gpmf_nodes(b"\x00\x00\x00\x00" + b"\x00" * 4) == ()


def test_parse_gpmf_nodes_stops_at_a_non_ascii_key() -> None:
    assert parse_gpmf_nodes(b"\xff\xff\xff\xff" + b"\x00" * 4) == ()


def test_parse_gpmf_nodes_stops_when_structure_size_is_zero() -> None:
    assert parse_gpmf_nodes(b"TEST\x00\x00\x00\x05") == ()


def test_parse_gpmf_nodes_keeps_valid_siblings_before_a_truncated_node() -> None:
    valid = _klv("AAAA", "B", 1, bytes([1, 2]))
    claims_five_bytes_but_has_none = b"BBBB" + bytes([0, 1, 0, 5])
    data = valid + claims_five_bytes_but_has_none

    nodes = parse_gpmf_nodes(data)

    assert [node.key for node in nodes] == ["AAAA"]
    assert nodes[0].payload == bytes([1, 2])


def test_parse_gpmf_nodes_only_recurses_into_container_type_nodes() -> None:
    leaf = _klv("GYRO", "s", 6, struct.pack(">hhh", 1, 2, 3))
    container = _klv("STRM", None, 1, leaf)

    (parsed_container,) = parse_gpmf_nodes(container)

    assert parsed_container.children != ()
    (parsed_leaf,) = parsed_container.children
    assert parsed_leaf.key == "GYRO"
    assert parsed_leaf.children == ()


def test_ffprobe_hex_dump_parser_handles_empty_input() -> None:
    assert parse_ffprobe_packet_data("") == b""


def test_ffprobe_hex_dump_parser_ignores_unmatched_lines_and_odd_trailing_nibbles() -> None:
    dump = """
not a hex dump line at all
00000000: 4445 56  DE
"""

    # "56" is a two-character remainder that never forms a complete 4-digit
    # group, so it is silently dropped rather than raising.
    assert parse_ffprobe_packet_data(dump) == b"DE"


def test_summarize_packet_with_no_recognized_nodes_is_none() -> None:
    assert summarize_gpmf_packet((), time_s=0.0, duration_s=1.0) is None


def test_summarize_packet_ignores_acceleration_only_payloads() -> None:
    # Pinning existing behavior: the packet is discarded unless it carries a
    # GYRO or SCEN stream, even when ACCL data is present.
    acceleration = struct.pack(">hhhhhh", 0, 0, 100, 0, 20, 100)
    payload = _klv("DEVC", None, 1, _stream(_klv("ACCL", "s", 6, acceleration)))

    sample = summarize_gpmf_packet(parse_gpmf_nodes(payload), time_s=0.0, duration_s=1.0)

    assert sample is None


def test_summarize_packet_clamps_negative_duration_to_zero() -> None:
    gyro = struct.pack(">hhhhhh", 20, 0, 0, 40, 0, 0)
    payload = _klv("DEVC", None, 1, _stream(_klv("GYRO", "s", 6, gyro)))

    sample = summarize_gpmf_packet(parse_gpmf_nodes(payload), time_s=0.0, duration_s=-5.0)

    assert sample is not None
    assert sample.duration_s == 0.0


def test_summarize_packet_without_scale_uses_raw_decoded_values() -> None:
    gyro = struct.pack(">hhhhhh", 20, 0, 0, 40, 0, 0)
    payload = _klv("DEVC", None, 1, _stream(_klv("GYRO", "s", 6, gyro)))  # no SCAL sibling

    sample = summarize_gpmf_packet(parse_gpmf_nodes(payload), time_s=0.0, duration_s=1.0)

    assert sample is not None
    assert sample.gyro_sustained_rad_s == pytest.approx(30.0)


def test_summarize_packet_scene_confidence_defaults_to_zero_without_scene_data() -> None:
    gyro = struct.pack(">hhhhhh", 20, 0, 0, 40, 0, 0)
    payload = _klv("DEVC", None, 1, _stream(_klv("GYRO", "s", 6, gyro)))

    sample = summarize_gpmf_packet(parse_gpmf_nodes(payload), time_s=0.0, duration_s=1.0)

    assert sample is not None
    assert sample.scene_confidence == 0.0
    assert sample.natural_scene_probability == 0.0
    assert sample.built_scene_probability == 0.0


def test_summarize_packet_computes_hue_weight_mean() -> None:
    gyro = struct.pack(">hhhhhh", 20, 0, 0, 40, 0, 0)
    payload = _klv(
        "DEVC",
        None,
        1,
        _stream(_klv("GYRO", "s", 6, gyro))
        + _stream(_klv("HUES", "?", 2, bytes([10, 100, 20, 200]))),
    )

    sample = summarize_gpmf_packet(parse_gpmf_nodes(payload), time_s=0.0, duration_s=1.0)

    assert sample is not None
    assert sample.hue_weight_mean == pytest.approx(150 / 255)


def _write_fake_clip(directory: Path, name: str = "clip.mp4") -> Path:
    path = directory / name
    path.write_bytes(b"not a real video, only used as a path for analyze_gpmf_metrics")
    return path


def _gpmf_hex_dump(raw: bytes) -> str:
    hex_text = raw.hex()
    groups = [hex_text[index : index + 4] for index in range(0, len(hex_text), 4)]
    return "00000000: " + " ".join(groups)


def _fake_gpmf_runner(hex_dump: str):
    def runner(command, **kwargs):
        if "-show_streams" in command:
            stdout = json.dumps({"streams": [{"index": 3, "codec_tag_string": "gpmd"}]})
        else:
            stdout = json.dumps(
                {"packets": [{"pts_time": "0.0", "duration_time": "1.0", "data": hex_dump}]}
            )
        return subprocess.CompletedProcess(command, 0, stdout=stdout, stderr="")

    return runner


def test_analyze_gpmf_metrics_rejects_a_missing_path(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="existing non-symlink"):
        analyze_gpmf_metrics(tmp_path / "missing.mp4", runner=lambda *a, **k: None)


def test_analyze_gpmf_metrics_rejects_an_unsupported_suffix(tmp_path: Path) -> None:
    path = _write_fake_clip(tmp_path, "clip.txt")

    with pytest.raises(ValueError, match="existing non-symlink"):
        analyze_gpmf_metrics(path, runner=lambda *a, **k: None)


def test_analyze_gpmf_metrics_rejects_a_symlink(tmp_path: Path) -> None:
    real = _write_fake_clip(tmp_path)
    link = tmp_path / "link.mp4"
    link.symlink_to(real)

    with pytest.raises(ValueError, match="existing non-symlink"):
        analyze_gpmf_metrics(link, runner=lambda *a, **k: None)


def test_analyze_gpmf_metrics_wraps_a_missing_ffprobe_binary(tmp_path: Path) -> None:
    path = _write_fake_clip(tmp_path)

    def runner(command, **kwargs):
        raise FileNotFoundError("ffprobe not installed")

    with pytest.raises(GpmfMetricError, match="could not read"):
        analyze_gpmf_metrics(path, runner=runner)


def test_analyze_gpmf_metrics_wraps_a_timed_out_ffprobe(tmp_path: Path) -> None:
    path = _write_fake_clip(tmp_path)

    def runner(command, **kwargs):
        raise subprocess.TimeoutExpired(cmd=command, timeout=1)

    with pytest.raises(GpmfMetricError, match="could not read"):
        analyze_gpmf_metrics(path, runner=runner)


def test_analyze_gpmf_metrics_wraps_a_nonzero_ffprobe_exit(tmp_path: Path) -> None:
    path = _write_fake_clip(tmp_path)

    def runner(command, **kwargs):
        return subprocess.CompletedProcess(command, 1, stdout="", stderr="boom")

    with pytest.raises(GpmfMetricError, match="ffprobe failed"):
        analyze_gpmf_metrics(path, runner=runner)


def test_analyze_gpmf_metrics_wraps_invalid_json(tmp_path: Path) -> None:
    path = _write_fake_clip(tmp_path)

    def runner(command, **kwargs):
        return subprocess.CompletedProcess(command, 0, stdout="not json", stderr="")

    with pytest.raises(GpmfMetricError, match="invalid GPMF JSON"):
        analyze_gpmf_metrics(path, runner=runner)


def test_analyze_gpmf_metrics_wraps_a_non_object_json_payload(tmp_path: Path) -> None:
    path = _write_fake_clip(tmp_path)

    def runner(command, **kwargs):
        return subprocess.CompletedProcess(command, 0, stdout="[]", stderr="")

    with pytest.raises(GpmfMetricError, match="unexpected GPMF payload"):
        analyze_gpmf_metrics(path, runner=runner)


def test_analyze_gpmf_metrics_requires_a_gpmd_stream(tmp_path: Path) -> None:
    path = _write_fake_clip(tmp_path)

    def runner(command, **kwargs):
        if "-show_streams" in command:
            stdout = json.dumps({"streams": [{"index": 0, "codec_tag_string": "vide"}]})
        else:
            stdout = json.dumps({"packets": []})
        return subprocess.CompletedProcess(command, 0, stdout=stdout, stderr="")

    with pytest.raises(GpmfMetricError, match="no GoPro GPMF metadata stream"):
        analyze_gpmf_metrics(path, runner=runner)


def test_analyze_gpmf_metrics_requires_at_least_one_decodable_sample(tmp_path: Path) -> None:
    path = _write_fake_clip(tmp_path)

    def runner(command, **kwargs):
        if "-show_streams" in command:
            stdout = json.dumps({"streams": [{"index": 3, "codec_tag_string": "gpmd"}]})
        else:
            stdout = json.dumps(
                {"packets": [{"pts_time": "0.0", "duration_time": "1.0", "data": ""}]}
            )
        return subprocess.CompletedProcess(command, 0, stdout=stdout, stderr="")

    with pytest.raises(GpmfMetricError, match="no camera/IMU samples"):
        analyze_gpmf_metrics(path, runner=runner)


def test_analyze_gpmf_metrics_end_to_end_with_a_synthetic_runner(tmp_path: Path) -> None:
    path = _write_fake_clip(tmp_path)
    gyro = struct.pack(">hhhhhh", 20, 0, 0, 40, 0, 0)
    raw = _klv("DEVC", None, 1, _stream(_klv("GYRO", "s", 6, gyro)))

    samples = analyze_gpmf_metrics(path, runner=_fake_gpmf_runner(_gpmf_hex_dump(raw)))

    assert len(samples) == 1
    assert samples[0].gyro_sustained_rad_s == pytest.approx(30.0)


def test_gpmf_dataclasses_carry_no_location_or_filesystem_fields() -> None:
    forbidden_terms = ("lat", "lon", "gps", "path", "file", "name", "coord")

    for dataclass_type in (GpmfMetricSample, GpmfWindowSummary, GpmfNode):
        field_names = [field.name.lower() for field in dataclasses.fields(dataclass_type)]
        for field_name in field_names:
            assert not any(term in field_name for term in forbidden_terms), (
                dataclass_type,
                field_name,
            )
