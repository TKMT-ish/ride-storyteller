"""Run a local-only, repeatable highlight-selection research pass."""

from __future__ import annotations

import argparse
import json
import shutil
import subprocess
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

from .apple_vision import (
    AppleVisionError,
    analyze_images_with_apple_vision,
    analyze_images_with_apple_vision_in_batches,
    build_apple_vision_probe,
)
from .gpmf_metrics import (
    GpmfMetricError,
    GpmfMetricSample,
    GpmfWindowSummary,
    analyze_gpmf_metrics,
    summarize_gpmf_window,
)
from .highlight_discovery import (
    HighlightDiscoveryError,
    HighlightWindowAnalysis,
    WindowFeatures,
    analyze_local_highlight_windows,
    build_highlight_clip_command,
)
from .highlight_quality import (
    HighlightWindowEvidence,
    QualitySelection,
    QualitySelectionEvaluation,
    QualitySelectionMethod,
    ScoredHighlightWindow,
    evaluate_quality_selection,
    export_quality_research_manifest,
    passes_strict_interest_gate,
    score_highlight_evidence,
    select_quality_highlights,
)
from .highlight_review import (
    evaluate_highlight_review,
    load_or_create_highlight_review,
)
from .metric_cache import PrivateMetricCache


class HighlightResearchError(RuntimeError):
    """Raised when a local research pass cannot produce reviewable evidence."""


DEFAULT_RESEARCH_TOP_K = 8
# Candidate clips are 12 seconds and the final selection requires 12 seconds
# of separation, so a six-second survey stride retains overlap without making
# on-device visual analysis inspect redundant near-identical windows.
DEFAULT_RESEARCH_STRIDE_S = 6.0
DEFAULT_RESEARCH_MINIMUM_SEPARATION_S = 12.0
DEFAULT_DIVERSITY_POOL_PER_METHOD = 96


@dataclass(frozen=True)
class HighlightResearchResult:
    analyzed_source_count: int
    analyzed_window_count: int
    strict_gate_count: int
    complete_evidence_count: int
    evidence_gate_count: int
    extracted_clip_count: int
    selections: dict[QualitySelectionMethod, tuple[QualitySelection, ...]]
    evaluations: dict[QualitySelectionMethod, QualitySelectionEvaluation]
    manifest_path: Path
    contact_sheet_path: Path
    review_path: Path


def run_local_highlight_research(
    gpx_path: Path,
    video_root: Path,
    catalog_path: Path,
    output_directory: Path,
    *,
    clip_duration_s: float = 12.0,
    stride_s: float = DEFAULT_RESEARCH_STRIDE_S,
    top_k: int = DEFAULT_RESEARCH_TOP_K,
    minimum_separation_s: float = DEFAULT_RESEARCH_MINIMUM_SEPARATION_S,
    duplicate_distance: float = 0.04,
    overwrite: bool = False,
    command_runner: Callable[..., subprocess.CompletedProcess[str]] = subprocess.run,
) -> HighlightResearchResult:
    """Analyze, select, extract, and evaluate local private ride footage."""
    _validate_private_output_directory(output_directory)
    manifest_path = output_directory / "highlight-research-manifest.json"
    if manifest_path.exists() and not overwrite:
        raise FileExistsError("highlight research output already exists")
    output_directory.mkdir(parents=True, exist_ok=True)
    metric_cache = PrivateMetricCache(output_directory / "metric-cache")

    analysis = analyze_local_highlight_windows(
        gpx_path,
        video_root,
        catalog_path,
        clip_duration_s=clip_duration_s,
        stride_s=stride_s,
        metric_cache=metric_cache,
    )
    strict_windows = tuple(
        window for window in analysis.windows if passes_strict_interest_gate(window)
    )
    if len(strict_windows) < top_k:
        raise HighlightResearchError("strict local highlight gate returned too few windows")

    evidence, center_frame_paths = _build_complete_evidence(
        strict_windows,
        analysis,
        output_directory,
        metric_cache=metric_cache,
        command_runner=command_runner,
    )
    scored = score_highlight_evidence(evidence)
    if len(scored) < top_k:
        raise HighlightResearchError("complete local highlight evidence is insufficient")
    diversity_pool = _build_diversity_pool(scored)
    if len(diversity_pool) < top_k:
        raise HighlightResearchError("local Vision diversity pool is insufficient")
    diversity_paths = tuple(
        center_frame_paths[(item.evidence.window.asset_id, item.evidence.window.start_offset_s)]
        for item in diversity_pool
    )
    probe_path = output_directory / ".apple-vision-probe"
    try:
        diversity_vision = analyze_images_with_apple_vision(diversity_paths, probe_path)
    except AppleVisionError as error:
        raise HighlightResearchError("local Vision diversity analysis failed") from error
    diversity_indices = tuple(item.evidence.feature_index for item in diversity_pool)
    vision_distance = _remap_vision_distance(diversity_indices, diversity_vision.distance)

    selections: dict[QualitySelectionMethod, tuple[QualitySelection, ...]] = {}
    evaluations: dict[QualitySelectionMethod, QualitySelectionEvaluation] = {}
    for method in QualitySelectionMethod:
        selected = select_quality_highlights(
            diversity_pool,
            method=method,
            distance=vision_distance,
            top_k=top_k,
            minimum_separation_s=minimum_separation_s,
            duplicate_distance=duplicate_distance,
        )
        if len(selected) < top_k:
            raise HighlightResearchError(
                f"{method.value} could not satisfy uniqueness and separation gates"
            )
        selections[method] = selected
        evaluations[method] = evaluate_quality_selection(
            selected,
            population=diversity_pool,
            distance=vision_distance,
        )

    review_path = output_directory / "highlight-review.json"
    review = load_or_create_highlight_review(review_path, selections)
    review_result = evaluate_highlight_review(selections, review)

    extracted_clip_count, thumbnail_paths = _extract_research_clips(
        selections,
        analysis,
        center_frame_paths,
        output_directory,
        overwrite=overwrite,
        command_runner=command_runner,
    )
    contact_sheet_path = _build_contact_sheet(
        thumbnail_paths,
        output_directory / "highlight-research-contact-sheet.jpg",
        overwrite=overwrite,
        command_runner=command_runner,
    )
    manifest_path.write_text(
        export_quality_research_manifest(
            selections,
            evaluations,
            analyzed_window_count=len(analysis.windows),
            strict_gate_count=len(strict_windows),
            complete_evidence_count=len(evidence),
            evidence_gate_count=len(scored),
        ),
        encoding="utf-8",
    )
    _write_private_research_state(
        output_directory / "research-private-state.json",
        selections,
        evaluations,
        analyzed_source_count=analysis.analyzed_source_count,
        analyzed_window_count=len(analysis.windows),
        strict_gate_count=len(strict_windows),
        complete_evidence_count=len(evidence),
        evidence_gate_count=len(scored),
        review_approved_count=len(review_result.approved_candidate_ids),
        review_awaiting_count=len(review_result.awaiting_candidate_ids),
        review_rejected_count=len(review_result.rejected_candidate_ids),
    )
    return HighlightResearchResult(
        analyzed_source_count=analysis.analyzed_source_count,
        analyzed_window_count=len(analysis.windows),
        strict_gate_count=len(strict_windows),
        complete_evidence_count=len(evidence),
        evidence_gate_count=len(scored),
        extracted_clip_count=extracted_clip_count,
        selections=selections,
        evaluations=evaluations,
        manifest_path=manifest_path,
        contact_sheet_path=contact_sheet_path,
        review_path=review_path,
    )


def build_frame_extraction_command(
    proxy_path: Path,
    output_path: Path,
    *,
    time_s: float,
    overwrite: bool,
) -> tuple[str, ...]:
    if time_s < 0:
        raise ValueError("highlight frame time must not be negative")
    return (
        "ffmpeg",
        "-hide_banner",
        "-loglevel",
        "error",
        "-y" if overwrite else "-n",
        "-ss",
        str(round(time_s, 6)),
        "-i",
        str(proxy_path),
        "-frames:v",
        "1",
        "-vf",
        "scale=640:-2",
        "-q:v",
        "3",
        str(output_path),
    )


def build_contact_sheet_command(
    thumbnail_directory: Path,
    output_path: Path,
    *,
    thumbnail_count: int,
    overwrite: bool,
) -> tuple[str, ...]:
    if thumbnail_count <= 0:
        raise ValueError("contact sheet requires at least one thumbnail")
    columns = min(5, thumbnail_count)
    rows = (thumbnail_count + columns - 1) // columns
    return (
        "ffmpeg",
        "-hide_banner",
        "-loglevel",
        "error",
        "-y" if overwrite else "-n",
        "-framerate",
        "1",
        "-pattern_type",
        "glob",
        "-i",
        str(thumbnail_directory / "*.jpg"),
        "-vf",
        (
            "scale=320:180:force_original_aspect_ratio=decrease,"
            f"pad=320:180:(ow-iw)/2:(oh-ih)/2,tile={columns}x{rows}"
        ),
        "-frames:v",
        "1",
        str(output_path),
    )


def _build_complete_evidence(
    strict_windows: tuple[WindowFeatures, ...],
    analysis: HighlightWindowAnalysis,
    output_directory: Path,
    *,
    metric_cache: PrivateMetricCache,
    command_runner: Callable[..., subprocess.CompletedProcess[str]],
) -> tuple[
    tuple[HighlightWindowEvidence, ...],
    dict[tuple[str, float], Path],
]:
    gpmf_by_asset: dict[str, tuple[GpmfMetricSample, ...]] = {}
    for asset_id in sorted({window.asset_id for window in strict_windows}):
        source_path = analysis.source_paths.get(asset_id)
        if source_path is None:
            continue
        try:
            gpmf_by_asset[asset_id] = metric_cache.load_or_analyze_gpmf_metrics(
                source_path,
                analyze_gpmf_metrics,
            )
        except GpmfMetricError:
            continue

    eligible: list[tuple[WindowFeatures, GpmfWindowSummary]] = []
    for window in strict_windows:
        samples = gpmf_by_asset.get(window.asset_id)
        if samples is None:
            continue
        summary = summarize_gpmf_window(
            samples,
            start_offset_s=window.start_offset_s,
            duration_s=window.duration_s,
        )
        if summary is not None and summary.coverage_ratio >= 0.75:
            eligible.append((window, summary))
    if not eligible:
        raise HighlightResearchError("no strict windows had complete local GPMF evidence")

    frame_directory = output_directory / "analysis-frames"
    frame_directory.mkdir(parents=True, exist_ok=True)
    frame_paths: list[Path] = []
    center_frame_paths: dict[tuple[str, float], Path] = {}
    for window_index, (window, _summary) in enumerate(eligible):
        proxy_path = analysis.proxy_paths.get(window.asset_id)
        if proxy_path is None:
            raise HighlightResearchError("strict window has no local proxy")
        offsets = (0.25, 0.50, 0.75)
        for frame_position, fraction in enumerate(offsets):
            frame_path = frame_directory / (
                f"window-{window_index:04d}-frame-{frame_position + 1}.jpg"
            )
            completed = command_runner(
                build_frame_extraction_command(
                    proxy_path,
                    frame_path,
                    time_s=window.start_offset_s + window.duration_s * fraction,
                    overwrite=True,
                ),
                check=False,
                capture_output=True,
                text=True,
                timeout=60,
            )
            if completed.returncode != 0 or not frame_path.is_file():
                raise HighlightResearchError("local highlight frame extraction failed")
            frame_paths.append(frame_path)
            if frame_position == 1:
                center_frame_paths[(window.asset_id, window.start_offset_s)] = frame_path

    probe_path = output_directory / ".apple-vision-probe"
    try:
        build_apple_vision_probe(
            Path(__file__).resolve().parents[2] / "tools" / "apple_vision_probe.m",
            probe_path,
            runner=command_runner,
        )
        vision_items = analyze_images_with_apple_vision_in_batches(
            tuple(frame_paths),
            probe_path,
            runner=command_runner,
        )
    except AppleVisionError as error:
        raise HighlightResearchError("on-device Apple Vision analysis failed") from error

    evidence: list[HighlightWindowEvidence] = []
    for window_index, (window, summary) in enumerate(eligible):
        start = window_index * 3
        frames = vision_items[start : start + 3]
        evidence.append(
            HighlightWindowEvidence(
                window=window,
                gpmf=summary,
                frames=frames,
                feature_index=start + 1,
            )
        )
    return tuple(evidence), center_frame_paths


def _build_diversity_pool(
    scored: tuple[ScoredHighlightWindow, ...],
    *,
    per_method: int = DEFAULT_DIVERSITY_POOL_PER_METHOD,
) -> tuple[ScoredHighlightWindow, ...]:
    """Bound costly Vision distances to the union of high-relevance candidates."""
    if per_method <= 0:
        raise ValueError("Vision diversity pool size must be positive")
    selected: dict[int, ScoredHighlightWindow] = {}
    for method in QualitySelectionMethod:
        ordered = sorted(
            scored,
            key=lambda item: (
                -item.score_for(method),
                item.evidence.window.timeline_s,
                item.evidence.window.asset_id,
                item.evidence.window.start_offset_s,
            ),
        )
        for item in ordered[:per_method]:
            selected[item.evidence.feature_index] = item
    return tuple(selected[index] for index in sorted(selected))


def _remap_vision_distance(
    feature_indices: tuple[int, ...],
    distance: Callable[[int, int], float],
) -> Callable[[int, int], float]:
    """Map a bounded Vision result back to evidence's global frame indices."""
    if len(set(feature_indices)) != len(feature_indices):
        raise ValueError("Vision diversity pool feature indices must be unique")
    local_index = {feature_index: index for index, feature_index in enumerate(feature_indices)}

    def remapped(first_index: int, second_index: int) -> float:
        try:
            return distance(local_index[first_index], local_index[second_index])
        except KeyError as error:
            raise KeyError("Vision distance requested outside the diversity pool") from error

    return remapped


def _extract_research_clips(
    selections: dict[QualitySelectionMethod, tuple[QualitySelection, ...]],
    analysis: HighlightWindowAnalysis,
    center_frame_paths: dict[tuple[str, float], Path],
    output_directory: Path,
    *,
    overwrite: bool,
    command_runner: Callable[..., subprocess.CompletedProcess[str]],
) -> tuple[int, tuple[Path, ...]]:
    thumbnail_directory = output_directory / "review-thumbnails"
    thumbnail_directory.mkdir(parents=True, exist_ok=True)
    thumbnails: list[Path] = []
    encoded: dict[tuple[str, float], Path] = {}
    extracted = 0
    for method in QualitySelectionMethod:
        method_directory = output_directory / method.value
        method_directory.mkdir(parents=True, exist_ok=True)
        for choice in selections[method]:
            window = choice.scored.evidence.window
            key = (window.asset_id, window.start_offset_s)
            output_path = method_directory / f"clip-{choice.rank:02d}.mp4"
            existing = encoded.get(key)
            if existing is not None:
                if output_path.exists() and overwrite:
                    output_path.unlink()
                output_path.hardlink_to(existing)
            else:
                source_path = analysis.source_paths.get(window.asset_id)
                if source_path is None:
                    raise HighlightResearchError("selected local source is unavailable")
                completed = command_runner(
                    build_highlight_clip_command(
                        source_path,
                        output_path,
                        start_offset_s=window.start_offset_s,
                        duration_s=window.duration_s,
                        overwrite=overwrite,
                    ),
                    check=False,
                    capture_output=True,
                    text=True,
                    timeout=max(120.0, window.duration_s * 10),
                )
                if completed.returncode != 0 or not output_path.is_file():
                    raise HighlightResearchError("local highlight clip extraction failed")
                encoded[key] = output_path
            extracted += 1
            center = center_frame_paths.get(key)
            if center is None:
                raise HighlightResearchError("selected highlight has no center frame")
            thumbnail = thumbnail_directory / f"{method.value}-clip-{choice.rank:02d}.jpg"
            shutil.copyfile(center, thumbnail)
            thumbnails.append(thumbnail)
    return extracted, tuple(thumbnails)


def _build_contact_sheet(
    thumbnails: tuple[Path, ...],
    output_path: Path,
    *,
    overwrite: bool,
    command_runner: Callable[..., subprocess.CompletedProcess[str]],
) -> Path:
    if not thumbnails:
        raise HighlightResearchError("contact sheet requires selected thumbnails")
    completed = command_runner(
        build_contact_sheet_command(
            thumbnails[0].parent,
            output_path,
            thumbnail_count=len(thumbnails),
            overwrite=overwrite,
        ),
        check=False,
        capture_output=True,
        text=True,
        timeout=120,
    )
    if completed.returncode != 0 or not output_path.is_file():
        raise HighlightResearchError("local highlight contact sheet creation failed")
    return output_path


def _write_private_research_state(
    path: Path,
    selections: dict[QualitySelectionMethod, tuple[QualitySelection, ...]],
    evaluations: dict[QualitySelectionMethod, QualitySelectionEvaluation],
    **counts: int,
) -> None:
    payload = {
        "schema_version": "local-highlight-private-state-v1",
        "privacy": {"external_data_sent": False, "private_output": True},
        "counts": counts,
        "methods": {
            method.value: {
                "evaluation": evaluations[method].to_dict(),
                "selections": [
                    {
                        "rank": choice.rank,
                        "asset_id": choice.asset_id,
                        "start_offset_s": choice.start_offset_s,
                        "relevance_score": choice.relevance_score,
                        "diversity_gain": choice.diversity_gain,
                    }
                    for choice in values
                ],
            }
            for method, values in selections.items()
        },
    }
    path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")


def _validate_private_output_directory(output_directory: Path) -> None:
    repository_root = Path(__file__).resolve().parents[2]
    resolved = output_directory.resolve()
    try:
        relative = resolved.relative_to(repository_root)
    except ValueError as error:
        raise ValueError("highlight research output must stay inside the repository") from error
    private_roots = (Path("private-media"), Path("data/private"), Path("media/private"))
    if not any(relative == root or root in relative.parents for root in private_roots):
        raise ValueError("highlight research output must use an ignored private directory")


def main() -> None:
    parser = argparse.ArgumentParser(description="Run local private highlight research")
    parser.add_argument("gpx", type=Path)
    parser.add_argument("video_root", type=Path)
    parser.add_argument("catalog", type=Path)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--top-k", type=int, default=DEFAULT_RESEARCH_TOP_K)
    parser.add_argument("--stride-s", type=float, default=DEFAULT_RESEARCH_STRIDE_S)
    parser.add_argument(
        "--minimum-separation-s",
        type=float,
        default=DEFAULT_RESEARCH_MINIMUM_SEPARATION_S,
    )
    parser.add_argument("--duplicate-distance", type=float, default=0.04)
    parser.add_argument("--overwrite", action="store_true")
    arguments = parser.parse_args()
    try:
        result = run_local_highlight_research(
            arguments.gpx,
            arguments.video_root,
            arguments.catalog,
            arguments.output,
            stride_s=arguments.stride_s,
            top_k=arguments.top_k,
            minimum_separation_s=arguments.minimum_separation_s,
            duplicate_distance=arguments.duplicate_distance,
            overwrite=arguments.overwrite,
        )
    except (HighlightResearchError, HighlightDiscoveryError) as error:
        raise SystemExit(str(error)) from error
    print(
        json.dumps(
            {
                "analyzed_source_count": result.analyzed_source_count,
                "analyzed_window_count": result.analyzed_window_count,
                "strict_gate_count": result.strict_gate_count,
                "complete_evidence_count": result.complete_evidence_count,
                "evidence_gate_count": result.evidence_gate_count,
                "extracted_clip_count": result.extracted_clip_count,
                "external_data_sent": False,
            },
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
