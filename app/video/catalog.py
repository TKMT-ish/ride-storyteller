"""Private local video-catalog matching and editor-friendly candidate exports."""

from __future__ import annotations

import csv
import io
import json
from dataclasses import dataclass
from datetime import datetime, timedelta
from enum import StrEnum
from pathlib import Path

from app.contracts import GpsEvent
from app.edit.candidate_planner import CandidateEditPlan


class VideoMatchStatus(StrEnum):
    MATCHED = "matched"
    NOT_FOUND = "not_found"


@dataclass(frozen=True)
class VideoCatalogEntry:
    asset_id: str
    file_name: str
    recorded_start_time: datetime
    duration_s: float
    mime_type: str = "video/mp4"

    def __post_init__(self) -> None:
        if not self.asset_id or not self.file_name or not self.mime_type:
            raise ValueError("asset_id, file_name, and mime_type are required")
        if self.recorded_start_time.tzinfo is None:
            raise ValueError("recorded_start_time must be timezone-aware")
        if self.duration_s <= 0:
            raise ValueError("duration_s must be positive")

    def to_dict(self) -> dict[str, object]:
        return {
            "asset_id": self.asset_id,
            "file_name": self.file_name,
            "recorded_start_time": self.recorded_start_time.isoformat().replace("+00:00", "Z"),
            "duration_s": self.duration_s,
            "mime_type": self.mime_type,
        }


@dataclass(frozen=True)
class VideoCatalog:
    entries: tuple[VideoCatalogEntry, ...]
    video_to_gps_offset_s: float = 0.0

    def __post_init__(self) -> None:
        identifiers = [entry.asset_id for entry in self.entries]
        if len(identifiers) != len(set(identifiers)):
            raise ValueError("video catalog asset_id values must be unique")

    def gps_start_time(self, entry: VideoCatalogEntry) -> datetime:
        """Return the GPS-clock equivalent of a camera-recorded start timestamp."""
        return entry.recorded_start_time + timedelta(seconds=self.video_to_gps_offset_s)

    def to_dict(self) -> dict[str, object]:
        return {
            "video_to_gps_offset_s": self.video_to_gps_offset_s,
            "entries": [entry.to_dict() for entry in self.entries],
        }


@dataclass(frozen=True)
class ResolvedCandidateClip:
    chapter_id: str
    event_id: str
    status: VideoMatchStatus
    asset_id: str | None
    file_name: str | None
    start_offset_s: float | None
    end_offset_s: float | None
    reason: str

    def to_dict(self) -> dict[str, object]:
        return {
            "chapter_id": self.chapter_id,
            "event_id": self.event_id,
            "status": self.status.value,
            "asset_id": self.asset_id,
            "file_name": self.file_name,
            "start_offset_s": self.start_offset_s,
            "end_offset_s": self.end_offset_s,
            "reason": self.reason,
        }


def load_video_catalog(path: Path) -> VideoCatalog:
    """Load a private JSON catalog; this function never probes video files."""
    raw = json.loads(path.read_text())
    entries = tuple(
        VideoCatalogEntry(
            asset_id=item["asset_id"],
            file_name=item["file_name"],
            recorded_start_time=datetime.fromisoformat(
                item["recorded_start_time"].replace("Z", "+00:00")
            ),
            duration_s=float(item["duration_s"]),
            mime_type=item.get("mime_type", "video/mp4"),
        )
        for item in raw.get("entries", [])
    )
    return VideoCatalog(
        entries=entries,
        video_to_gps_offset_s=float(raw.get("video_to_gps_offset_s", 0.0)),
    )


def resolve_candidate_clips(
    plan: CandidateEditPlan,
    events: tuple[GpsEvent, ...],
    catalog: VideoCatalog,
) -> tuple[ResolvedCandidateClip, ...]:
    """Map candidate events to catalog entries by corrected timestamps only."""
    events_by_id = {event.event_id: event for event in events}
    result: list[ResolvedCandidateClip] = []
    for clip in plan.clips:
        event = events_by_id.get(clip.event_id)
        if event is None:
            raise ValueError(f"candidate event is missing: {clip.event_id}")
        result.append(_resolve_event(clip.chapter_id, event, clip.requested_duration_s, catalog))
    return tuple(result)


def export_candidate_json(clips: tuple[ResolvedCandidateClip, ...]) -> str:
    return json.dumps(
        {"schema_version": "candidate-export-v1", "clips": [clip.to_dict() for clip in clips]},
        ensure_ascii=False,
        indent=2,
    )


def export_candidate_csv(clips: tuple[ResolvedCandidateClip, ...]) -> str:
    output = io.StringIO()
    writer = csv.DictWriter(
        output,
        fieldnames=(
            "chapter_id",
            "event_id",
            "status",
            "asset_id",
            "file_name",
            "start_offset_s",
            "end_offset_s",
            "reason",
        ),
    )
    writer.writeheader()
    writer.writerows(clip.to_dict() for clip in clips)
    return output.getvalue()


def write_candidate_exports(
    output_directory: Path, clips: tuple[ResolvedCandidateClip, ...]
) -> tuple[Path, Path]:
    """Write private candidate exports only to an explicit user-selected directory."""
    output_directory.mkdir(parents=True, exist_ok=True)
    json_path = output_directory / "ride-storyteller-candidates.json"
    csv_path = output_directory / "ride-storyteller-candidates.csv"
    json_path.write_text(export_candidate_json(clips))
    csv_path.write_text(export_candidate_csv(clips))
    return json_path, csv_path


def _resolve_event(
    chapter_id: str,
    event: GpsEvent,
    requested_duration_s: float,
    catalog: VideoCatalog,
) -> ResolvedCandidateClip:
    for entry in catalog.entries:
        gps_start = catalog.gps_start_time(entry)
        gps_end = gps_start + timedelta(seconds=entry.duration_s)
        # Treat catalog spans as half-open intervals so back-to-back files do
        # not both claim an event at the exact shared boundary.
        if not gps_start <= event.start_time < gps_end:
            continue
        event_offset_s = (event.start_time - gps_start).total_seconds()
        start_offset_s = max(0.0, event_offset_s - requested_duration_s / 2)
        end_offset_s = min(entry.duration_s, start_offset_s + requested_duration_s)
        start_offset_s = max(0.0, end_offset_s - requested_duration_s)
        return ResolvedCandidateClip(
            chapter_id=chapter_id,
            event_id=event.event_id,
            status=VideoMatchStatus.MATCHED,
            asset_id=entry.asset_id,
            file_name=entry.file_name,
            start_offset_s=start_offset_s,
            end_offset_s=end_offset_s,
            reason="補正後のGPS時刻が動画の記録区間に含まれます。",
        )
    return ResolvedCandidateClip(
        chapter_id=chapter_id,
        event_id=event.event_id,
        status=VideoMatchStatus.NOT_FOUND,
        asset_id=None,
        file_name=None,
        start_offset_s=None,
        end_offset_s=None,
        reason="補正後のGPS時刻を含む素材カタログ項目がありません。",
    )
