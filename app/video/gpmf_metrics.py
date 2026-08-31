"""Read privacy-safe visual and motion metrics from a local GoPro GPMF track.

Only camera/IMU keys used for local highlight ranking are decoded. GPS keys are
deliberately ignored even when they are present in the same metadata payload.
"""

from __future__ import annotations

import json
import math
import re
import struct
import subprocess
from collections.abc import Callable, Iterable, Iterator
from dataclasses import dataclass
from pathlib import Path
from statistics import fmean


class GpmfMetricError(RuntimeError):
    """Raised when a local GoPro metadata track cannot be decoded safely."""


@dataclass(frozen=True)
class GpmfNode:
    key: str
    type_code: int
    structure_size: int
    repeat: int
    payload: bytes
    children: tuple[GpmfNode, ...] = ()


@dataclass(frozen=True)
class GpmfMetricSample:
    time_s: float
    duration_s: float
    gyro_sustained_rad_s: float
    gyro_jitter_rad_s: float
    gyro_peak_rad_s: float
    acceleration_jitter_mps2: float
    iso_mean: float
    shutter_mean_s: float
    luma_mean: float
    uniformity_mean: float
    natural_scene_probability: float
    built_scene_probability: float
    scene_confidence: float
    hue_weight_mean: float


@dataclass(frozen=True)
class GpmfWindowSummary:
    gyro_sustained_rad_s: float
    center_gyro_sustained_rad_s: float
    gyro_jitter_rad_s: float
    gyro_peak_rad_s: float
    acceleration_jitter_mps2: float
    iso_mean: float
    shutter_mean_s: float
    luma_mean: float
    uniformity_mean: float
    natural_scene_probability: float
    built_scene_probability: float
    scene_confidence: float
    hue_weight_mean: float
    coverage_ratio: float


def parse_gpmf_nodes(data: bytes) -> tuple[GpmfNode, ...]:
    """Parse one aligned GPMF KLV payload without interpreting private GPS keys."""
    nodes: list[GpmfNode] = []
    offset = 0
    while offset + 8 <= len(data):
        header = data[offset : offset + 8]
        key_bytes = header[:4]
        if key_bytes == b"\x00\x00\x00\x00":
            break
        try:
            key = key_bytes.decode("ascii")
        except UnicodeDecodeError:
            break
        type_code = header[4]
        structure_size = header[5]
        repeat = int.from_bytes(header[6:8], "big")
        payload_size = structure_size * repeat
        payload_start = offset + 8
        payload_end = payload_start + payload_size
        if structure_size == 0 or payload_end > len(data):
            break
        payload = data[payload_start:payload_end]
        children = parse_gpmf_nodes(payload) if type_code == 0 else ()
        nodes.append(
            GpmfNode(
                key=key,
                type_code=type_code,
                structure_size=structure_size,
                repeat=repeat,
                payload=payload,
                children=children,
            )
        )
        offset = payload_start + ((payload_size + 3) // 4) * 4
    return tuple(nodes)


def parse_ffprobe_packet_data(data: str) -> bytes:
    """Convert ffprobe's hexadecimal packet dump back to its original bytes."""
    groups: list[str] = []
    for raw_line in data.splitlines():
        match = re.match(r"^[0-9a-fA-F]+:\s+(.+?)(?:\s{2,}|$)", raw_line.strip())
        if match is None:
            continue
        groups.extend(re.findall(r"\b[0-9a-fA-F]{4}\b", match.group(1)))
    return bytes.fromhex("".join(groups))


def analyze_gpmf_metrics(
    path: Path,
    *,
    runner: Callable[..., subprocess.CompletedProcess[str]] = subprocess.run,
) -> tuple[GpmfMetricSample, ...]:
    """Read camera/IMU metrics from the local MP4's GPMF stream."""
    if not path.is_file() or path.is_symlink() or path.suffix.lower() not in {".mp4", ".mov"}:
        raise ValueError("GPMF input must be an existing non-symlink MP4 or MOV file")
    streams = _run_json_command(
        (
            "ffprobe",
            "-v",
            "error",
            "-show_streams",
            "-show_entries",
            "stream=index,codec_tag_string",
            "-of",
            "json",
            str(path),
        ),
        runner=runner,
    )
    stream_index = next(
        (
            int(stream["index"])
            for stream in streams.get("streams", [])
            if stream.get("codec_tag_string") == "gpmd"
        ),
        None,
    )
    if stream_index is None:
        raise GpmfMetricError("local video has no GoPro GPMF metadata stream")
    packets = _run_json_command(
        (
            "ffprobe",
            "-v",
            "error",
            "-select_streams",
            str(stream_index),
            "-show_packets",
            "-show_entries",
            "packet=pts_time,duration_time,data",
            "-show_data",
            "-of",
            "json",
            str(path),
        ),
        runner=runner,
        timeout=600,
    )
    samples: list[GpmfMetricSample] = []
    for packet in packets.get("packets", []):
        raw = parse_ffprobe_packet_data(str(packet.get("data", "")))
        if not raw:
            continue
        sample = summarize_gpmf_packet(
            parse_gpmf_nodes(raw),
            time_s=float(packet.get("pts_time", 0.0)),
            duration_s=float(packet.get("duration_time", 1.0)),
        )
        if sample is not None:
            samples.append(sample)
    if not samples:
        raise GpmfMetricError("local GPMF analysis returned no camera/IMU samples")
    return tuple(samples)


def summarize_gpmf_packet(
    nodes: tuple[GpmfNode, ...],
    *,
    time_s: float,
    duration_s: float,
) -> GpmfMetricSample | None:
    """Summarize safe keys from a single timestamped GPMF packet."""
    streams = tuple(node for node in _walk(nodes) if node.key == "STRM")
    values: dict[str, list[object]] = {}
    for stream_node in streams:
        scale: tuple[float, ...] | None = None
        for node in stream_node.children:
            if node.key == "SCAL":
                decoded_scale = _decode_numeric(node)
                scale = tuple(float(value) for value in decoded_scale) or None
                continue
            if node.key in {
                "GYRO",
                "ACCL",
                "ISOE",
                "SHUT",
                "YAVG",
                "UNIF",
                "SCEN",
                "HUES",
            }:
                values.setdefault(node.key, []).append(_decode_sensor_node(node, scale))

    gyro_rows = _flatten_rows(values.get("GYRO", []))
    acceleration_rows = _flatten_rows(values.get("ACCL", []))
    scene_rows = _flatten_scene_rows(values.get("SCEN", []))
    if not gyro_rows and not scene_rows:
        return None

    gyro_sustained, gyro_jitter, gyro_peak = _vector_motion_summary(gyro_rows)
    _accel_sustained, acceleration_jitter, _accel_peak = _vector_motion_summary(acceleration_rows)
    scene_probabilities = {
        label: fmean(probabilities)
        for label in {label for row in scene_rows for label in row}
        if (probabilities := [row[label] for row in scene_rows if label in row])
    }
    natural = sum(scene_probabilities.get(label, 0.0) for label in ("SNOW", "WATR", "VEGE", "BEAC"))
    built = sum(scene_probabilities.get(label, 0.0) for label in ("URBA", "INDO"))
    confidence = max(scene_probabilities.values(), default=0.0)
    hue_weights = [
        float(weight)
        for decoded in values.get("HUES", [])
        for _hue, weight in decoded  # type: ignore[misc]
    ]
    return GpmfMetricSample(
        time_s=time_s,
        duration_s=max(duration_s, 0.0),
        gyro_sustained_rad_s=gyro_sustained,
        gyro_jitter_rad_s=gyro_jitter,
        gyro_peak_rad_s=gyro_peak,
        acceleration_jitter_mps2=acceleration_jitter,
        iso_mean=_mean_numeric(values.get("ISOE", [])),
        shutter_mean_s=_mean_numeric(values.get("SHUT", [])),
        luma_mean=_mean_numeric(values.get("YAVG", [])),
        uniformity_mean=_mean_numeric(values.get("UNIF", [])),
        natural_scene_probability=natural,
        built_scene_probability=built,
        scene_confidence=confidence,
        hue_weight_mean=fmean(hue_weights) / 255.0 if hue_weights else 0.0,
    )


def summarize_gpmf_window(
    samples: tuple[GpmfMetricSample, ...],
    *,
    start_offset_s: float,
    duration_s: float,
) -> GpmfWindowSummary | None:
    if start_offset_s < 0 or duration_s <= 0:
        raise ValueError("GPMF window must be a positive interval")
    end_offset_s = start_offset_s + duration_s
    selected = tuple(
        sample
        for sample in samples
        if sample.time_s < end_offset_s and sample.time_s + sample.duration_s > start_offset_s
    )
    if not selected:
        return None
    covered = sum(
        max(
            0.0,
            min(end_offset_s, sample.time_s + sample.duration_s)
            - max(start_offset_s, sample.time_s),
        )
        for sample in selected
    )
    center_time_s = start_offset_s + duration_s / 2
    center_sample = min(
        selected,
        key=lambda sample: abs(sample.time_s + sample.duration_s / 2 - center_time_s),
    )
    return GpmfWindowSummary(
        gyro_sustained_rad_s=fmean(sample.gyro_sustained_rad_s for sample in selected),
        center_gyro_sustained_rad_s=center_sample.gyro_sustained_rad_s,
        gyro_jitter_rad_s=fmean(sample.gyro_jitter_rad_s for sample in selected),
        gyro_peak_rad_s=max(sample.gyro_peak_rad_s for sample in selected),
        acceleration_jitter_mps2=fmean(sample.acceleration_jitter_mps2 for sample in selected),
        iso_mean=fmean(sample.iso_mean for sample in selected),
        shutter_mean_s=fmean(sample.shutter_mean_s for sample in selected),
        luma_mean=fmean(sample.luma_mean for sample in selected),
        uniformity_mean=fmean(sample.uniformity_mean for sample in selected),
        natural_scene_probability=fmean(sample.natural_scene_probability for sample in selected),
        built_scene_probability=fmean(sample.built_scene_probability for sample in selected),
        scene_confidence=fmean(sample.scene_confidence for sample in selected),
        hue_weight_mean=fmean(sample.hue_weight_mean for sample in selected),
        coverage_ratio=min(1.0, covered / duration_s),
    )


def _run_json_command(
    command: tuple[str, ...],
    *,
    runner: Callable[..., subprocess.CompletedProcess[str]],
    timeout: float = 60,
) -> dict[str, object]:
    try:
        completed = runner(
            command,
            check=False,
            capture_output=True,
            text=True,
            timeout=timeout,
        )
    except (FileNotFoundError, subprocess.TimeoutExpired) as error:
        raise GpmfMetricError("ffprobe could not read local GPMF metadata") from error
    if completed.returncode != 0:
        raise GpmfMetricError("ffprobe failed while reading local GPMF metadata")
    try:
        payload = json.loads(completed.stdout)
    except json.JSONDecodeError as error:
        raise GpmfMetricError("ffprobe returned invalid GPMF JSON") from error
    if not isinstance(payload, dict):
        raise GpmfMetricError("ffprobe returned an unexpected GPMF payload")
    return payload


def _walk(nodes: Iterable[GpmfNode]) -> Iterator[GpmfNode]:
    for node in nodes:
        yield node
        yield from _walk(node.children)


def _decode_sensor_node(
    node: GpmfNode,
    scale: tuple[float, ...] | None,
) -> object:
    if node.key == "SCEN":
        return tuple(
            {
                node.payload[offset : offset + 4].decode("ascii", errors="replace"): struct.unpack(
                    ">f", node.payload[offset + 4 : offset + 8]
                )[0]
            }
            for offset in range(0, len(node.payload), node.structure_size)
            if offset + 8 <= len(node.payload)
        )
    if node.key == "HUES":
        return tuple(
            (node.payload[offset], node.payload[offset + 1])
            for offset in range(0, len(node.payload), node.structure_size)
            if offset + 2 <= len(node.payload)
        )
    decoded = _decode_numeric(node)
    component_count = max(1, node.structure_size // _type_size(node.type_code))
    rows = [
        tuple(float(value) for value in decoded[index : index + component_count])
        for index in range(0, len(decoded), component_count)
    ]
    if scale:
        rows = [
            tuple(
                value / scale[min(component, len(scale) - 1)]
                if scale[min(component, len(scale) - 1)]
                else value
                for component, value in enumerate(row)
            )
            for row in rows
        ]
    return tuple(rows)


def _decode_numeric(node: GpmfNode) -> tuple[int | float, ...]:
    formats = {
        ord("b"): ">b",
        ord("B"): ">B",
        ord("s"): ">h",
        ord("S"): ">H",
        ord("l"): ">i",
        ord("L"): ">I",
        ord("f"): ">f",
        ord("d"): ">d",
    }
    format_code = formats.get(node.type_code)
    if format_code is None:
        return ()
    size = struct.calcsize(format_code)
    return tuple(
        struct.unpack(format_code, node.payload[offset : offset + size])[0]
        for offset in range(0, len(node.payload) - size + 1, size)
    )


def _type_size(type_code: int) -> int:
    return {
        ord("b"): 1,
        ord("B"): 1,
        ord("s"): 2,
        ord("S"): 2,
        ord("l"): 4,
        ord("L"): 4,
        ord("f"): 4,
        ord("d"): 8,
    }.get(type_code, 1)


def _flatten_rows(values: Iterable[object]) -> list[tuple[float, ...]]:
    return [
        tuple(float(component) for component in row)
        for decoded in values
        for row in decoded  # type: ignore[misc]
    ]


def _flatten_scene_rows(values: Iterable[object]) -> list[dict[str, float]]:
    return [
        {
            str(label): float(probability)
            for mapping in row
            for label, probability in mapping.items()
        }
        for decoded in values
        for row in (decoded,)  # type: ignore[misc]
    ]


def _mean_numeric(values: Iterable[object]) -> float:
    flattened = [
        float(component)
        for decoded in values
        for row in decoded  # type: ignore[misc]
        for component in row
    ]
    return fmean(flattened) if flattened else 0.0


def _vector_motion_summary(
    rows: list[tuple[float, ...]],
) -> tuple[float, float, float]:
    if not rows:
        return 0.0, 0.0, 0.0
    dimensions = min(len(row) for row in rows)
    means = tuple(fmean(row[index] for row in rows) for index in range(dimensions))
    sustained = math.sqrt(sum(value * value for value in means))
    residual_magnitudes = [
        math.sqrt(sum((row[index] - means[index]) ** 2 for index in range(dimensions)))
        for row in rows
    ]
    jitter = math.sqrt(fmean(value * value for value in residual_magnitudes))
    magnitudes = [
        math.sqrt(sum(row[index] * row[index] for index in range(dimensions))) for row in rows
    ]
    ordered = sorted(magnitudes)
    peak_index = max(0, math.ceil(0.95 * len(ordered)) - 1)
    return sustained, jitter, ordered[peak_index]
