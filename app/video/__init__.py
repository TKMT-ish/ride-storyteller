from typing import TYPE_CHECKING, Any

from .catalog import (
    ResolvedCandidateClip,
    VideoCatalog,
    VideoCatalogEntry,
    VideoMatchStatus,
    export_candidate_csv,
    export_candidate_json,
    load_video_catalog,
    resolve_candidate_clips,
    write_candidate_exports,
)
from .gemini_client import (
    GeminiVideoAnalysisError,
    GeminiVideoAnalyzer,
    GeminiVideoTransport,
    MockVideoAnalyzer,
    VideoAnalyzer,
)
from .inventory import (
    INVENTORY_SCHEMA_VERSION,
    SUPPORTED_VIDEO_SUFFIXES,
    LocalVideoInventory,
    LocalVideoInventoryEntry,
    build_local_video_inventory,
    export_local_video_inventory,
    write_local_video_inventory,
)
from .probe import (
    LocalVideoMetadata,
    VideoProbeError,
    export_local_video_metadata,
    probe_local_video_metadata,
    write_local_video_metadata,
)

if TYPE_CHECKING:
    from .vertex_transport import VertexAIGeminiVideoTransport


def __getattr__(name: str) -> Any:
    """Load the optional Google video transport only when explicitly requested."""
    if name == "VertexAIGeminiVideoTransport":
        from .vertex_transport import VertexAIGeminiVideoTransport

        return VertexAIGeminiVideoTransport
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")

__all__ = [
    "GeminiVideoAnalysisError",
    "GeminiVideoAnalyzer",
    "GeminiVideoTransport",
    "MockVideoAnalyzer",
    "VideoAnalyzer",
    "INVENTORY_SCHEMA_VERSION",
    "SUPPORTED_VIDEO_SUFFIXES",
    "LocalVideoInventory",
    "LocalVideoInventoryEntry",
    "LocalVideoMetadata",
    "ResolvedCandidateClip",
    "VideoCatalog",
    "VideoCatalogEntry",
    "VideoMatchStatus",
    "VideoProbeError",
    "export_candidate_csv",
    "export_candidate_json",
    "build_local_video_inventory",
    "export_local_video_inventory",
    "export_local_video_metadata",
    "load_video_catalog",
    "resolve_candidate_clips",
    "probe_local_video_metadata",
    "write_candidate_exports",
    "write_local_video_inventory",
    "write_local_video_metadata",
    "VertexAIGeminiVideoTransport",
]
