"""Fail-closed quality and diversity ranking for local ride highlights.

The selector combines privacy-safe aggregates from GPS, FFmpeg, GoPro GPMF,
and on-device Apple Vision.  It never confirms visual evidence; its output is a
shortlist for human review.
"""

from __future__ import annotations

import json
import math
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from enum import StrEnum
from statistics import fmean

from .apple_vision import VisionImageAnalysis
from .gpmf_metrics import GpmfWindowSummary
from .highlight_discovery import WindowFeatures

STRICT_MINIMUM_SPEED_MPS = 2.5
STRICT_P10_SPEED_MPS = 4.0
STRICT_CENTER_SPEED_MPS = 4.0
STRICT_MOVING_RATIO = 0.95
STRICT_MINIMUM_MOTION = 5.0
STRONG_TURN_MINIMUM_DEGREES = 18.0
STRONG_TURN_MINIMUM_CENTER_HEADING_DEGREES = 8.0
STRONG_TURN_MINIMUM_ACCUMULATED_DEGREES = 30.0
STRONG_TURN_MAXIMUM_PATH_EFFICIENCY = 0.985
MINIMUM_GPMF_COVERAGE = 0.75
MINIMUM_GYRO_SUSTAINED_RAD_S = 0.025
MINIMUM_CENTER_GYRO_SUSTAINED_RAD_S = 0.08
MINIMUM_ROAD_CONTEXT_RATIO = 2 / 3
DEFAULT_DUPLICATE_DISTANCE = 0.04
RESEARCH_MANIFEST_SCHEMA_VERSION = "local-highlight-research-v2"


class QualitySelectionMethod(StrEnum):
    QUALITY_FIRST = "01-quality-first"
    RIDE_DYNAMICS = "02-ride-dynamics"
    SCENIC_CONTEXT = "03-scenic-context"
    BALANCED_DIVERSE = "04-balanced-diverse"


class InterestLane(StrEnum):
    """Independent reasons a moving road segment may merit human review."""

    STRONG_TURN = "strong_turn"
    VISUAL_EVENT = "visual_event"


@dataclass(frozen=True)
class InterestGateResult:
    """Explain which local, non-semantic interest lanes a window passed."""

    continuous_motion: bool
    lanes: tuple[InterestLane, ...]

    @property
    def passes(self) -> bool:
        return self.continuous_motion and bool(self.lanes)


@dataclass(frozen=True)
class HighlightWindowEvidence:
    """Complete local evidence for one candidate window."""

    window: WindowFeatures
    gpmf: GpmfWindowSummary
    frames: tuple[VisionImageAnalysis, ...]
    feature_index: int

    def __post_init__(self) -> None:
        if len(self.frames) < 3:
            raise ValueError("highlight evidence requires at least three Vision frames")
        if self.feature_index < 0:
            raise ValueError("highlight evidence feature index must not be negative")
        if self.gpmf.coverage_ratio < MINIMUM_GPMF_COVERAGE:
            raise ValueError("highlight evidence has insufficient GPMF coverage")
        if len({frame.index for frame in self.frames}) != len(self.frames):
            raise ValueError("highlight Vision frame indices must be unique")
        if self.feature_index not in {frame.index for frame in self.frames}:
            raise ValueError("highlight feature index must reference one evidence frame")

    @property
    def aesthetic_mean(self) -> float:
        return fmean(frame.aesthetic_score for frame in self.frames)

    @property
    def aesthetic_minimum(self) -> float:
        return min(frame.aesthetic_score for frame in self.frames)

    @property
    def utility_ratio(self) -> float:
        return sum(frame.is_utility for frame in self.frames) / len(self.frames)

    @property
    def semantic_natural_score(self) -> float:
        natural = 0.0
        built = 0.0
        for frame in self.frames:
            for classification in frame.classifications:
                identifier = classification.identifier.casefold()
                if any(term in identifier for term in _NATURAL_TERMS):
                    natural += classification.confidence
                if any(term in identifier for term in _BUILT_TERMS):
                    built += classification.confidence
        scale = max(1, len(self.frames))
        return max(-1.0, min(1.0, (natural - built) / scale))

    @property
    def road_context_ratio(self) -> float:
        return sum(_frame_has_road_context(frame) for frame in self.frames) / len(self.frames)


@dataclass(frozen=True)
class ScoredHighlightWindow:
    evidence: HighlightWindowEvidence
    interest_lanes: tuple[InterestLane, ...]
    quality_score: float
    dynamics_score: float
    scenic_score: float
    balanced_score: float

    def score_for(self, method: QualitySelectionMethod) -> float:
        return {
            QualitySelectionMethod.QUALITY_FIRST: self.quality_score,
            QualitySelectionMethod.RIDE_DYNAMICS: self.dynamics_score,
            QualitySelectionMethod.SCENIC_CONTEXT: self.scenic_score,
            QualitySelectionMethod.BALANCED_DIVERSE: self.balanced_score,
        }[method]


@dataclass(frozen=True)
class QualitySelection:
    method: QualitySelectionMethod
    rank: int
    scored: ScoredHighlightWindow
    relevance_score: float
    diversity_gain: float

    @property
    def asset_id(self) -> str:
        return self.scored.evidence.window.asset_id

    @property
    def start_offset_s(self) -> float:
        return self.scored.evidence.window.start_offset_s


@dataclass(frozen=True)
class QualitySelectionEvaluation:
    selected_count: int
    unique_window_count: int
    aesthetic_mean: float
    aesthetic_minimum: float
    utility_frame_ratio: float
    mean_pairwise_distance: float
    minimum_pairwise_distance: float
    representativeness_distance: float
    natural_scene_probability_mean: float
    built_scene_probability_mean: float
    route_bucket_coverage: int
    hard_gate_violation_count: int

    def to_dict(self) -> dict[str, int | float]:
        return {
            "selected_count": self.selected_count,
            "unique_window_count": self.unique_window_count,
            "aesthetic_mean": round(self.aesthetic_mean, 6),
            "aesthetic_minimum": round(self.aesthetic_minimum, 6),
            "utility_frame_ratio": round(self.utility_frame_ratio, 6),
            "mean_pairwise_distance": round(self.mean_pairwise_distance, 6),
            "minimum_pairwise_distance": round(self.minimum_pairwise_distance, 6),
            "representativeness_distance": round(self.representativeness_distance, 6),
            "natural_scene_probability_mean": round(self.natural_scene_probability_mean, 6),
            "built_scene_probability_mean": round(self.built_scene_probability_mean, 6),
            "route_bucket_coverage": self.route_bucket_coverage,
            "hard_gate_violation_count": self.hard_gate_violation_count,
        }


_NATURAL_TERMS = (
    "beach",
    "coast",
    "forest",
    "grass",
    "hill",
    "lake",
    "landscape",
    "mountain",
    "nature",
    "ocean",
    "outdoor",
    "river",
    "sky",
    "snow",
    "tree",
    "valley",
    "vegetation",
    "water",
)
_BUILT_TERMS = (
    "building",
    "city",
    "indoor",
    "parking",
    "room",
    "urban",
)


def passes_strict_interest_gate(window: WindowFeatures) -> bool:
    """Keep only moving windows with a strong-turn or temporal visual-event signal."""
    return evaluate_interest_gate(window).passes


def evaluate_interest_gate(window: WindowFeatures) -> InterestGateResult:
    """Split interest into strict turning and non-semantic temporal-event lanes.

    The visual-event lane does not claim to identify an intersection, vehicle, or
    scenic subject. It only detects a sufficiently strong local change signal and
    leaves semantic interpretation to later human review.
    """
    continuous_motion = (
        window.mean_speed_mps >= 5.0
        and window.minimum_speed_mps >= STRICT_MINIMUM_SPEED_MPS
        and window.speed_p10_mps >= STRICT_P10_SPEED_MPS
        and window.center_speed_mps >= STRICT_CENTER_SPEED_MPS
        and window.moving_ratio >= STRICT_MOVING_RATIO
        and window.motion_mean >= STRICT_MINIMUM_MOTION
    )
    lanes: list[InterestLane] = []
    if continuous_motion and _passes_strong_turn_lane(window):
        lanes.append(InterestLane.STRONG_TURN)
    if continuous_motion and _passes_visual_event_lane(window):
        lanes.append(InterestLane.VISUAL_EVENT)
    return InterestGateResult(continuous_motion=continuous_motion, lanes=tuple(lanes))


def passes_complete_evidence_gate(evidence: HighlightWindowEvidence) -> bool:
    """Require sustained road context in addition to GPS and motion evidence."""
    center = next(frame for frame in evidence.frames if frame.index == evidence.feature_index)
    return (
        evaluate_interest_gate(evidence.window).passes
        and evidence.gpmf.gyro_sustained_rad_s >= MINIMUM_GYRO_SUSTAINED_RAD_S
        and evidence.gpmf.center_gyro_sustained_rad_s >= MINIMUM_CENTER_GYRO_SUSTAINED_RAD_S
        and evidence.road_context_ratio >= MINIMUM_ROAD_CONTEXT_RATIO
        and _frame_has_road_context(center)
        and evidence.utility_ratio <= 1 / 3
    )


def score_highlight_evidence(
    evidence: tuple[HighlightWindowEvidence, ...],
) -> tuple[ScoredHighlightWindow, ...]:
    """Normalize a complete evidence set and calculate four explainable scores."""
    eligible = tuple(item for item in evidence if passes_complete_evidence_gate(item))
    if not eligible:
        return ()
    metrics = {
        "aesthetic": _normalize([(item.aesthetic_mean + 1.0) / 2.0 for item in eligible]),
        "aesthetic_floor": _normalize([(item.aesthetic_minimum + 1.0) / 2.0 for item in eligible]),
        "nonutility": [1.0 - item.utility_ratio for item in eligible],
        "sharpness": _invert_normalize([item.window.blur_mean for item in eligible]),
        "entropy": _normalize([item.window.entropy_mean for item in eligible]),
        "exposure": [_exposure_quality(item.window) for item in eligible],
        "turn": _normalize(
            [
                0.3 * item.window.heading_change_degrees
                + item.window.center_heading_change_degrees
                + 0.2 * item.window.accumulated_heading_change_degrees
                + 100.0 * (1.0 - item.window.path_efficiency)
                for item in eligible
            ]
        ),
        "motion": _normalize([item.window.motion_mean for item in eligible]),
        "scene_change": _normalize([item.window.scene_change_mean for item in eligible]),
        "gyro_turn": _normalize(
            [
                0.4 * item.gpmf.gyro_sustained_rad_s + 0.6 * item.gpmf.center_gyro_sustained_rad_s
                for item in eligible
            ]
        ),
        "stability": _invert_normalize(
            [
                item.gpmf.gyro_jitter_rad_s + 0.2 * item.gpmf.acceleration_jitter_mps2
                for item in eligible
            ]
        ),
        "gpmf_natural": _normalize(
            [
                item.gpmf.natural_scene_probability - item.gpmf.built_scene_probability
                for item in eligible
            ]
        ),
        "semantic_natural": _normalize([item.semantic_natural_score for item in eligible]),
        "color": _normalize(
            [
                0.5 * item.window.saturation_mean + 50.0 * item.gpmf.hue_weight_mean
                for item in eligible
            ]
        ),
    }
    scored: list[ScoredHighlightWindow] = []
    for index, item in enumerate(eligible):
        quality = _weighted_at(
            metrics,
            index,
            aesthetic=0.30,
            aesthetic_floor=0.15,
            nonutility=0.10,
            sharpness=0.15,
            entropy=0.08,
            exposure=0.12,
            stability=0.10,
        )
        dynamics = _weighted_at(
            metrics,
            index,
            turn=0.32,
            gyro_turn=0.20,
            motion=0.20,
            scene_change=0.13,
            stability=0.10,
            nonutility=0.05,
        )
        scenic = _weighted_at(
            metrics,
            index,
            aesthetic=0.25,
            aesthetic_floor=0.10,
            gpmf_natural=0.22,
            semantic_natural=0.18,
            color=0.10,
            exposure=0.10,
            nonutility=0.05,
        )
        balanced = 0.35 * quality + 0.30 * dynamics + 0.35 * scenic
        scored.append(
            ScoredHighlightWindow(
                evidence=item,
                interest_lanes=evaluate_interest_gate(item.window).lanes,
                quality_score=round(quality, 9),
                dynamics_score=round(dynamics, 9),
                scenic_score=round(scenic, 9),
                balanced_score=round(balanced, 9),
            )
        )
    return tuple(scored)


def select_quality_highlights(
    scored: tuple[ScoredHighlightWindow, ...],
    *,
    method: QualitySelectionMethod,
    distance: Callable[[int, int], float],
    top_k: int = 10,
    minimum_separation_s: float = 30.0,
    duplicate_distance: float = DEFAULT_DUPLICATE_DISTANCE,
) -> tuple[QualitySelection, ...]:
    """Select unique clips with MMR diversity and route-bucket coverage."""
    if top_k <= 0:
        raise ValueError("highlight selection top_k must be positive")
    if minimum_separation_s < 0 or duplicate_distance < 0:
        raise ValueError("highlight separation limits must not be negative")
    ordered = tuple(
        sorted(
            scored,
            key=lambda item: (
                -item.score_for(method),
                item.evidence.window.timeline_s,
                item.evidence.window.asset_id,
                item.evidence.window.start_offset_s,
            ),
        )
    )
    if not ordered:
        return ()
    route_start = min(item.evidence.window.timeline_s for item in ordered)
    route_end = max(item.evidence.window.timeline_s for item in ordered)
    pairwise_values = [
        distance(first.evidence.feature_index, second.evidence.feature_index)
        for index, first in enumerate(ordered)
        for second in ordered[index + 1 :]
    ]
    distance_high = max(pairwise_values, default=1.0)
    selected: list[QualitySelection] = []
    selected_keys: set[tuple[str, float]] = set()
    selected_buckets: set[int] = set()
    while len(selected) < min(top_k, len(ordered)):
        best: tuple[float, ScoredHighlightWindow, float] | None = None
        route_modes = (
            (True, False)
            if method is QualitySelectionMethod.BALANCED_DIVERSE and len(selected_buckets) < 5
            else (False,)
        )
        for uncovered_only in route_modes:
            for candidate in ordered:
                window = candidate.evidence.window
                key = (window.asset_id, window.start_offset_s)
                if key in selected_keys:
                    continue
                bucket = _route_bucket(window.timeline_s, route_start, route_end)
                if uncovered_only and bucket in selected_buckets:
                    continue
                if any(
                    abs(window.timeline_s - choice.scored.evidence.window.timeline_s)
                    < minimum_separation_s
                    for choice in selected
                ):
                    continue
                raw_distances = [
                    distance(
                        candidate.evidence.feature_index,
                        choice.scored.evidence.feature_index,
                    )
                    for choice in selected
                ]
                if raw_distances and min(raw_distances) < duplicate_distance:
                    continue
                diversity = min(raw_distances, default=distance_high)
                normalized_diversity = (
                    min(1.0, diversity / distance_high) if distance_high > 0 else 0.0
                )
                coverage_bonus = 0.08 if bucket not in selected_buckets else 0.0
                relevance_weight = (
                    0.68 if method is QualitySelectionMethod.BALANCED_DIVERSE else 0.82
                )
                gain = (
                    relevance_weight * candidate.score_for(method)
                    + (1.0 - relevance_weight) * normalized_diversity
                    + coverage_bonus
                )
                contender = (gain, candidate, normalized_diversity)
                if best is None or _selection_order(contender) < _selection_order(best):
                    best = contender
            if best is not None:
                break
        if best is None:
            break
        gain, candidate, diversity = best
        selected.append(
            QualitySelection(
                method=method,
                rank=len(selected) + 1,
                scored=candidate,
                relevance_score=round(candidate.score_for(method), 9),
                diversity_gain=round(diversity, 9),
            )
        )
        window = candidate.evidence.window
        selected_keys.add((window.asset_id, window.start_offset_s))
        selected_buckets.add(_route_bucket(window.timeline_s, route_start, route_end))
    return tuple(selected)


def evaluate_quality_selection(
    selection: tuple[QualitySelection, ...],
    *,
    population: tuple[ScoredHighlightWindow, ...],
    distance: Callable[[int, int], float],
) -> QualitySelectionEvaluation:
    if not selection:
        return QualitySelectionEvaluation(0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0)
    evidence = tuple(choice.scored.evidence for choice in selection)
    pairwise = [
        distance(first.feature_index, second.feature_index)
        for index, first in enumerate(evidence)
        for second in evidence[index + 1 :]
    ]
    representativeness = fmean(
        min(distance(item.evidence.feature_index, chosen.feature_index) for chosen in evidence)
        for item in population
    )
    timeline_values = [item.evidence.window.timeline_s for item in population]
    route_start, route_end = min(timeline_values), max(timeline_values)
    buckets = {_route_bucket(item.window.timeline_s, route_start, route_end) for item in evidence}
    frame_count = sum(len(item.frames) for item in evidence)
    utility_count = sum(frame.is_utility for item in evidence for frame in item.frames)
    unique = {(item.window.asset_id, item.window.start_offset_s) for item in evidence}
    return QualitySelectionEvaluation(
        selected_count=len(selection),
        unique_window_count=len(unique),
        aesthetic_mean=fmean(item.aesthetic_mean for item in evidence),
        aesthetic_minimum=min(item.aesthetic_minimum for item in evidence),
        utility_frame_ratio=utility_count / frame_count,
        mean_pairwise_distance=fmean(pairwise) if pairwise else 0.0,
        minimum_pairwise_distance=min(pairwise) if pairwise else 0.0,
        representativeness_distance=representativeness,
        natural_scene_probability_mean=fmean(
            item.gpmf.natural_scene_probability for item in evidence
        ),
        built_scene_probability_mean=fmean(item.gpmf.built_scene_probability for item in evidence),
        route_bucket_coverage=len(buckets),
        hard_gate_violation_count=sum(not passes_complete_evidence_gate(item) for item in evidence),
    )


def export_quality_research_manifest(
    selections: Mapping[QualitySelectionMethod, tuple[QualitySelection, ...]],
    evaluations: Mapping[QualitySelectionMethod, QualitySelectionEvaluation],
    *,
    analyzed_window_count: int,
    strict_gate_count: int,
    complete_evidence_count: int,
    evidence_gate_count: int,
) -> str:
    """Serialize only path-free, coordinate-free comparison data."""
    payload = {
        "schema_version": RESEARCH_MANIFEST_SCHEMA_VERSION,
        "privacy": {
            "private_data_used": True,
            "external_data_sent": False,
            "coordinates_in_manifest": False,
            "absolute_paths_in_manifest": False,
            "recorded_timestamps_in_manifest": False,
            "vision_labels_in_manifest": False,
            "visual_evidence_auto_confirmed": False,
        },
        "gates": {
            "minimum_speed_mps": STRICT_MINIMUM_SPEED_MPS,
            "speed_p10_mps": STRICT_P10_SPEED_MPS,
            "center_speed_mps": STRICT_CENTER_SPEED_MPS,
            "moving_ratio": STRICT_MOVING_RATIO,
            "minimum_visual_motion": STRICT_MINIMUM_MOTION,
            "strong_turn": {
                "minimum_turn_degrees": STRONG_TURN_MINIMUM_DEGREES,
                "minimum_center_heading_change_degrees": (
                    STRONG_TURN_MINIMUM_CENTER_HEADING_DEGREES
                ),
                "minimum_accumulated_turn_degrees": STRONG_TURN_MINIMUM_ACCUMULATED_DEGREES,
                "maximum_path_efficiency": STRONG_TURN_MAXIMUM_PATH_EFFICIENCY,
            },
            "visual_event": {
                "minimum_scene_change": _MINIMUM_VISUAL_EVENT_SCENE_CHANGE,
                "minimum_scene_peak_ratio": _MINIMUM_VISUAL_EVENT_SCENE_PEAK_RATIO,
                "minimum_motion_std": _MINIMUM_VISUAL_EVENT_MOTION_STD,
            },
            "minimum_gpmf_coverage": MINIMUM_GPMF_COVERAGE,
            "minimum_gyro_sustained_rad_s": MINIMUM_GYRO_SUSTAINED_RAD_S,
            "minimum_center_gyro_sustained_rad_s": (MINIMUM_CENTER_GYRO_SUSTAINED_RAD_S),
            "minimum_road_context_ratio": MINIMUM_ROAD_CONTEXT_RATIO,
        },
        "summary": {
            "analyzed_window_count": analyzed_window_count,
            "strict_gate_count": strict_gate_count,
            "complete_evidence_count": complete_evidence_count,
            "evidence_gate_count": evidence_gate_count,
            "method_count": len(selections),
        },
        "methods": {
            method.value: {
                "evaluation": evaluations[method].to_dict(),
                "candidates": [
                    {
                        "rank": choice.rank,
                        "candidate_id": f"candidate-{choice.rank:02d}",
                        "relevance_score": round(choice.relevance_score, 6),
                        "diversity_gain": round(choice.diversity_gain, 6),
                        "interest_lanes": [
                            lane.value for lane in choice.scored.interest_lanes
                        ],
                        "output_file_name": f"clip-{choice.rank:02d}.mp4",
                    }
                    for choice in values
                ],
            }
            for method, values in selections.items()
        },
    }
    return json.dumps(payload, ensure_ascii=False, indent=2) + "\n"


_MINIMUM_VISUAL_EVENT_SCENE_CHANGE = 12.0
_MINIMUM_VISUAL_EVENT_SCENE_PEAK_RATIO = 0.20
_MINIMUM_VISUAL_EVENT_MOTION_STD = 1.5


def _passes_strong_turn_lane(window: WindowFeatures) -> bool:
    return (
        window.heading_change_degrees >= STRONG_TURN_MINIMUM_DEGREES
        and window.center_heading_change_degrees >= STRONG_TURN_MINIMUM_CENTER_HEADING_DEGREES
        and window.accumulated_heading_change_degrees >= STRONG_TURN_MINIMUM_ACCUMULATED_DEGREES
        and window.path_efficiency <= STRONG_TURN_MAXIMUM_PATH_EFFICIENCY
    )


def _passes_visual_event_lane(window: WindowFeatures) -> bool:
    return (
        window.scene_change_mean >= _MINIMUM_VISUAL_EVENT_SCENE_CHANGE
        and window.scene_change_peak_ratio >= _MINIMUM_VISUAL_EVENT_SCENE_PEAK_RATIO
        and window.motion_std >= _MINIMUM_VISUAL_EVENT_MOTION_STD
    )


def _selection_order(
    contender: tuple[float, ScoredHighlightWindow, float],
) -> tuple[float, float, float, str, float]:
    gain, candidate, diversity = contender
    window = candidate.evidence.window
    return (
        -gain,
        -candidate.balanced_score,
        -diversity,
        window.asset_id,
        window.start_offset_s,
    )


def _route_bucket(value: float, start: float, end: float, bucket_count: int = 5) -> int:
    if math.isclose(start, end):
        return 0
    fraction = max(0.0, min(1.0, (value - start) / (end - start)))
    return min(bucket_count - 1, int(fraction * bucket_count))


def _normalize(values: list[float]) -> list[float]:
    if not values:
        return []
    low, high = min(values), max(values)
    if math.isclose(low, high):
        return [0.5 for _ in values]
    return [(value - low) / (high - low) for value in values]


def _invert_normalize(values: list[float]) -> list[float]:
    return [1.0 - value for value in _normalize(values)]


def _weighted_at(metrics: Mapping[str, list[float]], index: int, **weights: float) -> float:
    total = sum(weights.values())
    if total <= 0:
        raise ValueError("highlight score weights must be positive")
    return sum(metrics[name][index] * weight for name, weight in weights.items()) / total


def _exposure_quality(window: WindowFeatures) -> float:
    midpoint = max(0.0, 1.0 - abs(window.luma_mean - 128.0) / 128.0)
    range_quality = min(1.0, max(0.0, window.dynamic_range_mean / 180.0))
    return 0.7 * midpoint + 0.3 * range_quality


def _frame_has_road_context(frame: VisionImageAnalysis) -> bool:
    return any(
        (
            classification.identifier.casefold() == "road"
            or classification.identifier.casefold().startswith("road_")
        )
        and classification.confidence >= 0.20
        for classification in frame.classifications
    )
