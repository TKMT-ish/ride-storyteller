"""Keep what Gemini said about a ride's footage, in the ride's own package.

A judgement that lives only in memory has to be paid for again every time the
film is recut. Analysis is the one step here that costs money, so its answers
are written down beside the exports they describe, and a rerun reads them
instead of buying them twice.

Writing them down also makes them checkable. A selection can be argued with
only if the judgement behind it can be read back, which is why the record
keeps the model's own description and scores rather than only the verdict
that came out of them.

The record names events and assets, so it is a private artifact like its
neighbours: it belongs in the git-ignored package and never in a public
export, a browser payload, or a handoff note. `app.gemini_selection` is what
turns it into a decision, and that module's report quotes none of it.
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass
from pathlib import Path
from tempfile import mkstemp

from app.contracts import VideoAnalysis

VIDEO_ANALYSIS_RECORD_SCHEMA_VERSION = "video-analysis-record-v1"

VIDEO_ANALYSIS_RECORD_FILE_NAME = "gemini-video-analysis.json"

# Providers whose judgement was actually paid for. Anything else is a
# stand-in, and a film built on it is not evidence of what a model saw.
BOUGHT_ANALYSIS_PROVIDERS = frozenset({"gemini"})


class VideoAnalysisRecordError(ValueError):
    """Raised when an analysis record cannot be written or trusted."""


@dataclass(frozen=True)
class AnalysedEvent:
    """One event's window and what the model made of it."""

    event_id: str
    analysis: VideoAnalysis

    def __post_init__(self) -> None:
        if not self.event_id:
            raise ValueError("an analysed event needs its event")

    def to_dict(self) -> dict[str, object]:
        return {
            "event_id": self.event_id,
            "asset_id": self.analysis.asset_id,
            "start_offset_s": round(self.analysis.start_offset_s, 3),
            "end_offset_s": round(self.analysis.end_offset_s, 3),
            "visual_description": self.analysis.visual_description,
            "road_type": self.analysis.road_type,
            "scenery_tags": list(self.analysis.scenery_tags),
            "weather_visible": self.analysis.weather_visible,
            "visual_interest_score": self.analysis.visual_interest_score,
            "story_relevance_score": self.analysis.story_relevance_score,
            "confidence": self.analysis.confidence,
            "analysis_provider": self.analysis.analysis_provider,
            "rider_visible": self.analysis.rider_visible,
            "stationary": self.analysis.stationary,
            "road_event": self.analysis.road_event,
            "photogenic_score": self.analysis.photogenic_score,
            "highlight_subject": self.analysis.highlight_subject,
            "place_kind": self.analysis.place_kind,
            "place_name": self.analysis.place_name,
        }


@dataclass(frozen=True)
class VideoAnalysisRecord:
    """Every judgement bought for one ride."""

    analysed: tuple[AnalysedEvent, ...]

    def __post_init__(self) -> None:
        event_ids = [item.event_id for item in self.analysed]
        if len(event_ids) != len(set(event_ids)):
            raise ValueError("an analysis record must not judge one event twice")

    def analysis_for(self, event_id: str) -> VideoAnalysis | None:
        """What the model said about this event, or nothing if it never saw it."""
        for item in self.analysed:
            if item.event_id == event_id:
                return item.analysis
        return None

    def to_dict(self) -> dict[str, object]:
        return {
            "schema_version": VIDEO_ANALYSIS_RECORD_SCHEMA_VERSION,
            "analysed_count": len(self.analysed),
            "analysed": [item.to_dict() for item in self.analysed],
        }


def load_video_analysis_record(path: Path) -> VideoAnalysisRecord:
    """Read a record back, refusing anything this version cannot trust."""
    if path.is_symlink() or not path.is_file():
        raise VideoAnalysisRecordError("the analysis record is unavailable")
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise VideoAnalysisRecordError("the analysis record is unreadable") from error
    if not isinstance(payload, dict):
        raise VideoAnalysisRecordError("the analysis record is malformed")
    if payload.get("schema_version") != VIDEO_ANALYSIS_RECORD_SCHEMA_VERSION:
        raise VideoAnalysisRecordError("unsupported analysis record schema")
    try:
        return VideoAnalysisRecord(
            tuple(
                AnalysedEvent(
                    event_id=str(item["event_id"]),
                    analysis=VideoAnalysis(
                        asset_id=str(item["asset_id"]),
                        start_offset_s=float(item["start_offset_s"]),
                        end_offset_s=float(item["end_offset_s"]),
                        visual_description=str(item["visual_description"]),
                        road_type=str(item["road_type"]),
                        scenery_tags=tuple(str(tag) for tag in item["scenery_tags"]),
                        weather_visible=str(item["weather_visible"]),
                        visual_interest_score=float(item["visual_interest_score"]),
                        story_relevance_score=float(item["story_relevance_score"]),
                        confidence=float(item["confidence"]),
                        analysis_provider=str(item["analysis_provider"]),
                        # Records bought before the model was asked about the
                        # rider say "unknown"; the words are read instead.
                        rider_visible=str(item.get("rider_visible", "unknown")),
                        stationary=str(item.get("stationary", "unknown")),
                        road_event=str(item.get("road_event", "unknown")),
                        photogenic_score=(
                            float(item["photogenic_score"])
                            if item.get("photogenic_score") is not None
                            else None
                        ),
                        highlight_subject=str(item.get("highlight_subject", "unknown")),
                        place_kind=str(item.get("place_kind", "unknown")),
                        place_name=(str(item["place_name"]) if item.get("place_name") else None),
                    ),
                )
                for item in payload["analysed"]
            )
        )
    except (KeyError, TypeError, ValueError) as error:
        raise VideoAnalysisRecordError("the analysis record is malformed") from error


def write_video_analysis_record(
    output_path: Path, record: VideoAnalysisRecord, *, overwrite: bool = True
) -> Path:
    """Persist the record atomically.

    Overwriting is the default because a rerun's judgements replace an older
    run's. What must not happen is a half-written record surviving a crash and
    being read as complete, so it is written beside its destination and moved
    across only when whole.
    """
    if output_path.is_symlink():
        raise VideoAnalysisRecordError("the analysis record path is unsafe")
    if output_path.exists() and not overwrite:
        raise FileExistsError("an analysis record already exists at that path")
    output_path.parent.mkdir(parents=True, exist_ok=True)
    file_descriptor, temporary_name = mkstemp(
        dir=output_path.parent, prefix=f".{output_path.name}.", suffix=".tmp", text=True
    )
    temporary_path = Path(temporary_name)
    try:
        with os.fdopen(file_descriptor, "w", encoding="utf-8") as handle:
            handle.write(json.dumps(record.to_dict(), ensure_ascii=False, indent=2) + "\n")
        os.replace(temporary_path, output_path)
    except BaseException:
        temporary_path.unlink(missing_ok=True)
        raise
    return output_path
