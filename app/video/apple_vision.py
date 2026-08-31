"""Optional macOS-only local Vision analysis for highlight candidates."""

from __future__ import annotations

import json
import subprocess
from collections.abc import Callable
from dataclasses import dataclass, replace
from pathlib import Path


class AppleVisionError(RuntimeError):
    """Raised when the local Apple Vision helper fails closed."""


@dataclass(frozen=True)
class VisionClassification:
    identifier: str
    confidence: float


@dataclass(frozen=True)
class VisionImageAnalysis:
    index: int
    aesthetic_score: float
    is_utility: bool
    classifications: tuple[VisionClassification, ...]


@dataclass(frozen=True)
class VisionAnalysisResult:
    items: tuple[VisionImageAnalysis, ...]
    feature_distances: dict[tuple[int, int], float]

    def distance(self, first_index: int, second_index: int) -> float:
        if first_index == second_index:
            return 0.0
        key = tuple(sorted((first_index, second_index)))
        if key not in self.feature_distances:
            raise KeyError("Vision feature distance is unavailable")
        return self.feature_distances[key]


DEFAULT_APPLE_VISION_BATCH_SIZE = 96


def build_apple_vision_probe(
    source_path: Path,
    output_path: Path,
    *,
    runner: Callable[..., subprocess.CompletedProcess[str]] = subprocess.run,
) -> Path:
    """Compile the repository's Objective-C Vision helper into a private cache."""
    if not source_path.is_file() or source_path.suffix != ".m":
        raise ValueError("Apple Vision probe source must be an Objective-C file")
    _validate_private_or_temporary_path(output_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    module_cache = output_path.parent / "clang-module-cache"
    module_cache.mkdir(parents=True, exist_ok=True)
    command = (
        "xcrun",
        "clang",
        "-fobjc-arc",
        f"-fmodules-cache-path={module_cache}",
        "-framework",
        "Foundation",
        "-framework",
        "Vision",
        "-framework",
        "CoreGraphics",
        str(source_path),
        "-O2",
        "-o",
        str(output_path),
    )
    try:
        completed = runner(
            command,
            check=False,
            capture_output=True,
            text=True,
            timeout=120,
        )
    except (FileNotFoundError, subprocess.TimeoutExpired) as error:
        raise AppleVisionError("Apple Vision probe compiler could not run") from error
    if completed.returncode != 0 or not output_path.is_file():
        raise AppleVisionError("Apple Vision probe compilation failed")
    return output_path


def analyze_images_with_apple_vision(
    image_paths: tuple[Path, ...],
    probe_path: Path,
    *,
    include_distances: bool = True,
    runner: Callable[..., subprocess.CompletedProcess[str]] = subprocess.run,
) -> VisionAnalysisResult:
    """Analyze local images without returning or persisting their paths.

    ``include_distances=False`` is intentionally available for large candidate
    sets.  It retains the per-image quality observations while avoiding the
    quadratic feature-distance matrix.
    """
    if not image_paths:
        raise ValueError("Apple Vision analysis requires at least one image")
    if not probe_path.is_file() or probe_path.is_symlink():
        raise ValueError("Apple Vision probe executable is unavailable")
    if any(
        not path.is_file()
        or path.is_symlink()
        or path.suffix.lower() not in {".jpg", ".jpeg", ".png"}
        for path in image_paths
    ):
        raise ValueError("Apple Vision inputs must be existing non-symlink images")
    command = (
        str(probe_path),
        *(("--no-distances",) if not include_distances else ()),
        *(str(path) for path in image_paths),
    )
    try:
        completed = runner(
            command,
            check=False,
            capture_output=True,
            text=True,
            timeout=max(120.0, len(image_paths) * 10.0),
        )
    except (FileNotFoundError, subprocess.TimeoutExpired) as error:
        raise AppleVisionError("local Apple Vision analysis could not run") from error
    if completed.returncode != 0:
        raise AppleVisionError("local Apple Vision analysis failed")
    return parse_apple_vision_output(
        completed.stdout,
        expected_count=len(image_paths),
        require_distances=include_distances,
    )


def analyze_images_with_apple_vision_in_batches(
    image_paths: tuple[Path, ...],
    probe_path: Path,
    *,
    batch_size: int = DEFAULT_APPLE_VISION_BATCH_SIZE,
    runner: Callable[..., subprocess.CompletedProcess[str]] = subprocess.run,
) -> tuple[VisionImageAnalysis, ...]:
    """Return local per-image observations in bounded, distance-free batches.

    The global indices preserve the ordering of ``image_paths`` so downstream
    evidence can still identify its center frame.  Feature distances are
    deliberately omitted here and are calculated later for a small selection
    pool only.
    """
    if batch_size <= 0:
        raise ValueError("Apple Vision batch size must be positive")
    items: list[VisionImageAnalysis] = []
    for start in range(0, len(image_paths), batch_size):
        result = analyze_images_with_apple_vision(
            image_paths[start : start + batch_size],
            probe_path,
            include_distances=False,
            runner=runner,
        )
        items.extend(replace(item, index=start + item.index) for item in result.items)
    return tuple(items)


def parse_apple_vision_output(
    output: str,
    *,
    expected_count: int,
    require_distances: bool = True,
) -> VisionAnalysisResult:
    try:
        payload = json.loads(output)
    except json.JSONDecodeError as error:
        raise AppleVisionError("Apple Vision probe returned invalid JSON") from error
    if payload.get("schemaVersion") != "ride-apple-vision-v1":
        raise AppleVisionError("Apple Vision probe schema is unsupported")
    raw_items = payload.get("items")
    if not isinstance(raw_items, list) or len(raw_items) != expected_count:
        raise AppleVisionError("Apple Vision probe returned an incomplete item set")
    items = tuple(
        VisionImageAnalysis(
            index=int(item["index"]),
            aesthetic_score=float(item["aestheticScore"]),
            is_utility=bool(item["isUtility"]),
            classifications=tuple(
                VisionClassification(
                    identifier=str(label["identifier"]),
                    confidence=float(label["confidence"]),
                )
                for label in item.get("classifications", [])
            ),
        )
        for item in raw_items
    )
    if tuple(item.index for item in items) != tuple(range(expected_count)):
        raise AppleVisionError("Apple Vision item indices are not contiguous")
    distances: dict[tuple[int, int], float] = {}
    for raw_distance in payload.get("distances", []):
        first = int(raw_distance["firstIndex"])
        second = int(raw_distance["secondIndex"])
        if not 0 <= first < second < expected_count:
            raise AppleVisionError("Apple Vision feature distance indices are invalid")
        distance = float(raw_distance["distance"])
        if distance < 0:
            raise AppleVisionError("Apple Vision feature distance must not be negative")
        distances[(first, second)] = distance
    expected_distances = expected_count * (expected_count - 1) // 2
    if require_distances and len(distances) != expected_distances:
        raise AppleVisionError("Apple Vision feature distance matrix is incomplete")
    return VisionAnalysisResult(items=items, feature_distances=distances)


def _validate_private_or_temporary_path(path: Path) -> None:
    resolved = path.resolve()
    temporary_roots = (Path("/private/tmp"), Path("/tmp"), Path("/private/var/folders"))
    if any(resolved == root or root in resolved.parents for root in temporary_roots):
        return
    repository_root = Path(__file__).resolve().parents[2]
    try:
        relative = resolved.relative_to(repository_root)
    except ValueError as error:
        raise ValueError("Apple Vision probe output must use a private cache") from error
    private_roots = (Path("private-media"), Path("data/private"), Path("media/private"))
    if not any(relative == root or root in relative.parents for root in private_roots):
        raise ValueError("Apple Vision probe output must use a private cache")
