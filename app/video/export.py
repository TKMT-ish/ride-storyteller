"""Create private editor-candidate exports from a GPX and a video metadata catalog."""

from __future__ import annotations

import argparse
from pathlib import Path

from app.agents import RuleBasedStoryPlanner
from app.edit import build_candidate_edit_plan
from app.gps import consolidate_events, extract_events, parse_gpx
from app.video.catalog import load_video_catalog, resolve_candidate_clips, write_candidate_exports


def export_private_candidates(
    gpx_path: Path, catalog_path: Path, output_directory: Path
) -> tuple[Path, Path]:
    """Write JSON/CSV only to the caller-selected directory; no media is uploaded."""
    route = parse_gpx(gpx_path)
    events = consolidate_events(extract_events(route, asset_name_hint="catalog_match_required"))
    story_plan = RuleBasedStoryPlanner().plan(route.summary, events, target_duration_s=480)
    candidate_plan = build_candidate_edit_plan(story_plan, events)
    clips = resolve_candidate_clips(candidate_plan, events, load_video_catalog(catalog_path))
    return write_candidate_exports(output_directory, clips)


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Create local-only Ride Storyteller JSON and CSV editor candidates."
    )
    parser.add_argument("gpx", type=Path, help="private Garmin GPX path")
    parser.add_argument("catalog", type=Path, help="private video catalog JSON path")
    parser.add_argument("--output", type=Path, required=True, help="private output directory")
    args = parser.parse_args()
    json_path, csv_path = export_private_candidates(args.gpx, args.catalog, args.output)
    print(f"Created local-only exports: {json_path.name}, {csv_path.name}")


if __name__ == "__main__":
    main()
