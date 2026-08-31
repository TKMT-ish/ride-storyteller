from typing import TYPE_CHECKING, Any

from .catalog import (
    ResolvedCandidateClip,
    VideoCatalog,
    VideoCatalogEntry,
    VideoMatchStatus,
    export_candidate_csv,
    export_candidate_json,
    load_resolved_candidate_export,
    load_video_catalog,
    resolve_candidate_clips,
    select_video_backed_events,
    write_candidate_exports,
)
from .gemini_client import (
    GeminiVideoAnalysisError,
    GeminiVideoAnalyzer,
    GeminiVideoTransport,
    MockVideoAnalyzer,
    VideoAnalyzer,
)
from .highlight_quality import (
    HighlightWindowEvidence,
    InterestGateResult,
    InterestLane,
    QualitySelection,
    QualitySelectionEvaluation,
    QualitySelectionMethod,
    evaluate_interest_gate,
    passes_complete_evidence_gate,
    passes_strict_interest_gate,
    score_highlight_evidence,
    select_quality_highlights,
)
from .highlight_research import (
    HighlightResearchError,
    HighlightResearchResult,
    run_local_highlight_research,
)
from .highlight_review import (
    HIGHLIGHT_REVIEW_SCHEMA_VERSION,
    HighlightReview,
    HighlightReviewDecision,
    HighlightReviewReason,
    HighlightReviewResult,
    HighlightReviewStatus,
    build_highlight_review_template,
    evaluate_highlight_review,
    highlight_review_candidate_id,
    load_highlight_review,
    load_or_create_highlight_review,
    update_highlight_review_decision,
    write_highlight_review,
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
from .local_catalog import (
    LOCAL_VIDEO_CATALOG_SCHEMA_VERSION,
    SOURCE_VIDEO_SUFFIXES,
    LocalCatalogIssue,
    LocalCatalogIssueCode,
    LocalVideoCatalogBuild,
    build_local_video_catalog,
    export_local_video_catalog,
    write_local_video_catalog,
)
from .local_clips import (
    LOCAL_REVIEW_CLIP_MANIFEST_SCHEMA_VERSION,
    LocalClipExtractionError,
    LocalReviewClip,
    export_local_review_clip_manifest,
    extract_local_review_clips,
    load_local_review_clip_manifest,
    write_local_review_clip_manifest,
)
from .metric_cache import (
    PRIVATE_METRIC_CACHE_SCHEMA_VERSION,
    PrivateMetricCache,
)
from .probe import (
    LocalVideoMetadata,
    VideoProbeError,
    export_local_video_metadata,
    probe_local_video_metadata,
    write_local_video_metadata,
)
from .review import (
    LOCAL_EVIDENCE_REVIEW_SCHEMA_VERSION,
    LocalEvidenceDecision,
    LocalEvidenceReview,
    LocalEvidenceReviewResult,
    build_local_evidence_review_template,
    evaluate_local_evidence_review,
    load_local_evidence_review,
    write_local_evidence_review,
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
    "HighlightResearchError",
    "HighlightResearchResult",
    "HighlightReview",
    "HighlightReviewDecision",
    "HighlightReviewReason",
    "HighlightReviewResult",
    "HighlightReviewStatus",
    "HighlightWindowEvidence",
    "InterestGateResult",
    "InterestLane",
    "LocalCatalogIssue",
    "LocalCatalogIssueCode",
    "LocalClipExtractionError",
    "LocalEvidenceDecision",
    "LocalEvidenceReview",
    "LocalEvidenceReviewResult",
    "LocalReviewClip",
    "LocalVideoCatalogBuild",
    "LocalVideoMetadata",
    "PrivateMetricCache",
    "LOCAL_VIDEO_CATALOG_SCHEMA_VERSION",
    "LOCAL_EVIDENCE_REVIEW_SCHEMA_VERSION",
    "LOCAL_REVIEW_CLIP_MANIFEST_SCHEMA_VERSION",
    "PRIVATE_METRIC_CACHE_SCHEMA_VERSION",
    "HIGHLIGHT_REVIEW_SCHEMA_VERSION",
    "ResolvedCandidateClip",
    "QualitySelection",
    "QualitySelectionEvaluation",
    "QualitySelectionMethod",
    "VideoCatalog",
    "VideoCatalogEntry",
    "VideoMatchStatus",
    "VideoProbeError",
    "SOURCE_VIDEO_SUFFIXES",
    "export_candidate_csv",
    "export_candidate_json",
    "build_local_video_inventory",
    "build_highlight_review_template",
    "build_local_video_catalog",
    "build_local_evidence_review_template",
    "export_local_video_inventory",
    "export_local_video_catalog",
    "export_local_review_clip_manifest",
    "export_local_video_metadata",
    "extract_local_review_clips",
    "evaluate_local_evidence_review",
    "evaluate_interest_gate",
    "evaluate_highlight_review",
    "highlight_review_candidate_id",
    "load_video_catalog",
    "load_resolved_candidate_export",
    "load_local_evidence_review",
    "load_local_review_clip_manifest",
    "load_highlight_review",
    "load_or_create_highlight_review",
    "update_highlight_review_decision",
    "resolve_candidate_clips",
    "select_video_backed_events",
    "probe_local_video_metadata",
    "passes_complete_evidence_gate",
    "passes_strict_interest_gate",
    "run_local_highlight_research",
    "score_highlight_evidence",
    "select_quality_highlights",
    "write_candidate_exports",
    "write_local_video_inventory",
    "write_local_video_catalog",
    "write_local_evidence_review",
    "write_local_review_clip_manifest",
    "write_local_video_metadata",
    "write_highlight_review",
    "VertexAIGeminiVideoTransport",
]
