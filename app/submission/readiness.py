"""Safe local preflight for work that can be finished before real video arrives."""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from pathlib import Path

_REQUIRED_DOCUMENTS = (
    "README.md",
    "devpost-submission.md",
    "docs/ui-localization.md",
    "docs/google-story-copy.md",
    "docs/licensing.md",
    "docs/agent-platform-deployment-preflight.md",
    "docs/public-demo-hosting.md",
    "docs/cloud-run-public-demo.md",
    "docs/submission/project-writeup-en.md",
    "docs/submission/architecture.md",
    "docs/submission/demo-script-en.md",
    "docs/submission/demo-subtitles-en.srt",
    "docs/submission/demo-recording-runbook-ja.md",
    "docs/submission/screenshot-plan.md",
    "docs/submission/devpost-registration-worksheet-ja.md",
    "docs/submission/ibm-bob-capture-checklist-ja.md",
    "docs/submission/ibm-bob-evidence.md",
    "docs/submission/ibm-bob-review-sanitized.md",
    "docs/submission/judging-alignment.md",
    "docs/submission/official-rules-audit.md",
    "docs/submission/public-repository-preflight-ja.md",
    "docs/submission/technical-evidence.md",
    "docs/submission/test-evidence.md",
    "docs/submission/assets/01-home-en-public-safe.jpg",
    "docs/submission/assets/02-agent-accepted-en.jpg",
    "docs/submission/assets/03-agent-missing-asset-en.jpg",
    "docs/submission/assets/04-candidate-evidence-blocked-en.jpg",
    "docs/submission/assets/05-story-plan-synthetic-en.jpg",
    "docs/submission/assets/06-ibm-bob-video-evidence-gate.png",
)
_REQUIRED_DEVPOST_SECTIONS = (
    "# Ride Storyteller",
    "## One-line Summary",
    "## Problem",
    "## Solution",
    "## Why This Matters",
    "## How We Used AI",
    "## How We Used Codex",
    "## Key Features",
    "## Architecture",
    "## Testing Instructions",
    "## Public Demo Link",
    "## Public Repository Link",
    "## Demo Video",
    "## Screenshot Shot List",
    "## Submission Readiness Notes",
    "## Known Limitations",
    "## TODO Official Form Fields",
)
_LICENSE_FILE_NAMES = ("LICENSE", "LICENSE.txt", "LICENSE.md")
_OSI_LICENSE_MARKERS = {
    "AGPL-3.0": (
        "GNU AFFERO GENERAL PUBLIC LICENSE",
        "Version 3, 19 November 2007",
        "Remote Network Interaction",
        "END OF TERMS AND CONDITIONS",
    ),
    "Apache-2.0": (
        "Apache License",
        "Version 2.0, January 2004",
        "END OF TERMS AND CONDITIONS",
    ),
    "BSD": (
        "Redistribution and use in source and binary forms",
        "THIS SOFTWARE IS PROVIDED BY THE COPYRIGHT HOLDERS",
    ),
    "GPL": ("GNU GENERAL PUBLIC LICENSE", "NO WARRANTY"),
    "MIT": (
        "Permission is hereby granted, free of charge",
        'THE SOFTWARE IS PROVIDED "AS IS"',
    ),
    "MPL-2.0": (
        "Mozilla Public License Version 2.0",
        "This Source Code Form is subject to the terms",
    ),
}
_REQUIRED_IGNORE_PATTERNS = (
    ".env",
    ".devpost-submission-answers.json",
    "*.gpx",
    "*.fit",
    "*.mp4",
    "*.mov",
    "*.lrv",
    "private-media/",
)
_PRIVATE_SUFFIXES = {".gpx", ".fit", ".mp4", ".mov", ".lrv"}
_PUBLIC_TEXT_SUFFIXES = {
    ".css",
    ".html",
    ".js",
    ".json",
    ".md",
    ".py",
    ".srt",
    ".toml",
    ".txt",
    ".yaml",
    ".yml",
}
_SECRET_PATTERNS = {
    "google_api_key": re.compile(r"AIza[0-9A-Za-z_-]{30,}"),
    "private_key": re.compile(r"-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----"),
}
_EXCLUDED_DIRECTORIES = {
    ".git",
    ".pytest_cache",
    ".ruff_cache",
    ".venv",
    "__pycache__",
    "data/private",
    "media/private",
    "private-media",
}


@dataclass(frozen=True)
class OfflineReadinessCheck:
    check_id: str
    ready: bool
    detail: str

    def to_dict(self) -> dict[str, object]:
        return {"check_id": self.check_id, "ready": self.ready, "detail": self.detail}


@dataclass(frozen=True)
class OfflineSubmissionReadiness:
    checks: tuple[OfflineReadinessCheck, ...]
    external_gates: tuple[str, ...]
    media_gates: tuple[str, ...]

    @property
    def offline_preparation_complete(self) -> bool:
        return all(check.ready for check in self.checks)

    def to_dict(self) -> dict[str, object]:
        return {
            "offline_preparation_complete": self.offline_preparation_complete,
            "checks": [check.to_dict() for check in self.checks],
            "external_gates": list(self.external_gates),
            "media_gates": list(self.media_gates),
            "submission_ready": False,
            "submission_ready_reason": (
                "This local preflight intentionally does not claim external registration, "
                "publication, public hosting, or real-media evidence."
            ),
        }


def build_offline_submission_readiness(
    root: Path = Path("."),
) -> OfflineSubmissionReadiness:
    """Inspect only filenames and text configuration needed for offline preparation."""
    root = root.resolve()
    missing_documents = tuple(
        relative for relative in _REQUIRED_DOCUMENTS if not _is_nonempty_file(root / relative)
    )
    ignore_file = root / ".gitignore"
    ignore_text = ignore_file.read_text(encoding="utf-8") if ignore_file.is_file() else ""
    missing_ignores = tuple(
        pattern for pattern in _REQUIRED_IGNORE_PATTERNS if pattern not in ignore_text
    )
    private_candidates = _private_candidates(root)
    secret_candidates = _secret_candidates(root)
    license_result = _recognized_osi_license(root)
    missing_devpost_sections = _missing_devpost_sections(root / "devpost-submission.md")
    devpost_state_path = root / ".devpost-hackathon-state.json"
    devpost_state_present = devpost_state_path.is_file()
    rules_acknowledged = _rules_acknowledged(devpost_state_path)
    source_control_present = (root / ".git").is_dir()

    return OfflineSubmissionReadiness(
        checks=(
            OfflineReadinessCheck(
                "submission_documents",
                not missing_documents,
                "complete" if not missing_documents else "missing: " + ", ".join(missing_documents),
            ),
            OfflineReadinessCheck(
                "devpost_draft_sections",
                not missing_devpost_sections,
                (
                    "complete"
                    if not missing_devpost_sections
                    else "missing headings: " + ", ".join(missing_devpost_sections)
                ),
            ),
            OfflineReadinessCheck(
                "osi_license",
                license_result is not None,
                (
                    f"recognized license: {license_result}"
                    if license_result is not None
                    else "missing or unrecognized root OSI license file"
                ),
            ),
            OfflineReadinessCheck(
                "private_data_ignore_rules",
                not missing_ignores,
                "complete"
                if not missing_ignores
                else "missing ignore patterns: " + ", ".join(missing_ignores),
            ),
            OfflineReadinessCheck(
                "no_private_media_in_public_source_tree",
                not private_candidates,
                "complete"
                if not private_candidates
                else "private file candidates: " + ", ".join(private_candidates),
            ),
            OfflineReadinessCheck(
                "no_secret_markers_in_public_text",
                not secret_candidates,
                "complete"
                if not secret_candidates
                else "secret markers: " + ", ".join(secret_candidates),
            ),
        ),
        external_gates=(
            (
                "Devpost workflow state is present and records local rules acknowledgment; "
                "live registration and submission status must be re-verified through Devpost."
                if rules_acknowledged
                else (
                    "Devpost workflow state is present, but local rules acknowledgment is "
                    "incomplete or unreadable."
                    if devpost_state_present
                    else "Initialize the Devpost hackathon workflow, authenticate, and review "
                    "the current official rules."
                )
            ),
            (
                "Local source control exists; public repository publication still needs "
                "explicit confirmation."
                if source_control_present
                else "Initialize source control, review the first commit, then publish only "
                "with explicit confirmation."
            ),
            "Re-verify current registration and official form requirements immediately before "
            "submission.",
            "Publish and verify the public application only with explicit approval.",
            (
                "Publish the reviewed repository under the selected OSI license only with "
                "explicit approval."
            ),
            "Record and publish the final public three-minute English demo video.",
        ),
        media_gates=(
            "Build the local source-video inventory after the private files become accessible.",
            "Validate camera timestamps, GPS clock correction, and proxy strategy locally.",
            "Run the approved real-video Gemini analysis and complete visual-evidence review.",
            "Record the final English demo with real end-to-end evidence.",
        ),
    )


def _rules_acknowledged(path: Path) -> bool:
    """Read only the local rules flag; Devpost-owned status is always verified live."""
    if not path.is_file():
        return False
    try:
        state = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError):
        return False
    return state.get("rules_acknowledged") is True


def _recognized_osi_license(root: Path) -> str | None:
    """Recognize a small set of common OSI-license texts at the repository root."""
    for file_name in _LICENSE_FILE_NAMES:
        path = root / file_name
        if not path.is_file():
            continue
        contents = path.read_text(encoding="utf-8", errors="ignore")
        for identifier, markers in _OSI_LICENSE_MARKERS.items():
            if len(contents) >= 500 and all(marker in contents for marker in markers):
                return identifier
    return None


def _is_nonempty_file(path: Path) -> bool:
    return path.is_file() and path.stat().st_size > 0


def _missing_devpost_sections(path: Path) -> tuple[str, ...]:
    if not path.is_file():
        return _REQUIRED_DEVPOST_SECTIONS
    contents = path.read_text(encoding="utf-8", errors="ignore")
    return tuple(heading for heading in _REQUIRED_DEVPOST_SECTIONS if heading not in contents)


def _private_candidates(root: Path) -> tuple[str, ...]:
    candidates: list[str] = []
    for path in root.rglob("*"):
        if not path.is_file() or path.suffix.lower() not in _PRIVATE_SUFFIXES:
            continue
        relative = path.relative_to(root)
        if _is_excluded(relative):
            continue
        candidates.append(relative.as_posix())
    return tuple(sorted(candidates))


def _secret_candidates(root: Path) -> tuple[str, ...]:
    candidates: list[str] = []
    for path in root.rglob("*"):
        if not path.is_file() or path.suffix.lower() not in _PUBLIC_TEXT_SUFFIXES:
            continue
        relative = path.relative_to(root)
        if relative.as_posix() == ".env" or _is_excluded(relative):
            continue
        contents = path.read_text(encoding="utf-8", errors="ignore")
        for label, pattern in _SECRET_PATTERNS.items():
            if pattern.search(contents):
                candidates.append(f"{relative.as_posix()}:{label}")
    return tuple(sorted(candidates))


def _is_excluded(relative: Path) -> bool:
    as_posix = relative.as_posix()
    return any(
        as_posix == excluded or as_posix.startswith(excluded + "/")
        for excluded in _EXCLUDED_DIRECTORIES
    )


def main() -> None:
    report = build_offline_submission_readiness()
    print(json.dumps(report.to_dict(), ensure_ascii=False, indent=2))
    if not report.offline_preparation_complete:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
