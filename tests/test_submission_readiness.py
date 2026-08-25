from pathlib import Path

from app.submission import build_offline_submission_readiness

REQUIRED_DOCUMENTS = (
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

REQUIRED_DEVPOST_SECTIONS = (
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

MIT_LICENSE_SAMPLE = """MIT License

Copyright (c) 2026 Test Author

Permission is hereby granted, free of charge, to any person obtaining a copy
of this software and associated documentation files (the "Software"), to deal
in the Software without restriction, including without limitation the rights
to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
copies of the Software, and to permit persons to whom the Software is
furnished to do so, subject to the following conditions:

The above copyright notice and this permission notice shall be included in all
copies or substantial portions of the Software.

THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE
SOFTWARE.
"""

AGPL_LICENSE_SAMPLE = """GNU AFFERO GENERAL PUBLIC LICENSE
Version 3, 19 November 2007

Copyright (C) 2007 Free Software Foundation, Inc.
Everyone is permitted to copy and distribute verbatim copies of this license
document, but changing it is not allowed.

The GNU Affero General Public License is a free, copyleft license for software
and other kinds of works, specifically designed to ensure cooperation with the
community in the case of network server software. The terms allow recipients
to run, modify, and convey the covered work, subject to the complete license.

Remote Network Interaction requires a modified version used through a computer
network to offer its Corresponding Source to those users. The complete license
contains the detailed conditions for conveying source and object code.

THERE IS NO WARRANTY FOR THE PROGRAM, TO THE EXTENT PERMITTED BY APPLICABLE LAW.

END OF TERMS AND CONDITIONS
"""


def _prepared_root(root: Path) -> Path:
    for relative in REQUIRED_DOCUMENTS:
        path = root / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("prepared", encoding="utf-8")
    (root / "devpost-submission.md").write_text(
        "\n\n".join(REQUIRED_DEVPOST_SECTIONS),
        encoding="utf-8",
    )
    (root / ".gitignore").write_text(
        ".env\n.devpost-submission-answers.json\n"
        "*.gpx\n*.fit\n*.mp4\n*.mov\n*.lrv\nprivate-media/\n",
        encoding="utf-8",
    )
    (root / "LICENSE").write_text(AGPL_LICENSE_SAMPLE, encoding="utf-8")
    return root


def test_offline_submission_preflight_passes_complete_local_preparation(tmp_path: Path) -> None:
    root = _prepared_root(tmp_path)
    (root / ".git").mkdir()
    report = build_offline_submission_readiness(root)

    assert report.offline_preparation_complete is True
    assert report.to_dict()["submission_ready"] is False
    assert report.external_gates
    assert report.media_gates
    assert "live public repository URL" in report.external_gates[1]
    assert all("publication still needs" not in gate for gate in report.external_gates)


def test_offline_submission_preflight_uses_local_rules_state_without_claiming_registration(
    tmp_path: Path,
) -> None:
    root = _prepared_root(tmp_path)
    (root / ".devpost-hackathon-state.json").write_text(
        '{"rules_acknowledged": true}',
        encoding="utf-8",
    )

    report = build_offline_submission_readiness(root)

    assert "records local rules acknowledgment" in report.external_gates[0]
    assert "live registration and submission status must be re-verified" in (
        report.external_gates[0]
    )
    assert all("Complete Devpost registration" not in gate for gate in report.external_gates)


def test_offline_submission_preflight_rejects_unreadable_rules_state(tmp_path: Path) -> None:
    root = _prepared_root(tmp_path)
    (root / ".devpost-hackathon-state.json").write_text("not-json", encoding="utf-8")

    report = build_offline_submission_readiness(root)

    assert "incomplete or unreadable" in report.external_gates[0]


def test_offline_submission_preflight_reports_missing_documents(tmp_path: Path) -> None:
    root = _prepared_root(tmp_path)
    (root / "docs/submission/demo-script-en.md").unlink()

    report = build_offline_submission_readiness(root)

    assert report.offline_preparation_complete is False
    document_check = next(
        check for check in report.checks if check.check_id == "submission_documents"
    )
    assert "demo-script-en.md" in document_check.detail


def test_offline_submission_preflight_requires_ibm_bob_evidence_image(
    tmp_path: Path,
) -> None:
    root = _prepared_root(tmp_path)
    (root / "docs/submission/assets/06-ibm-bob-video-evidence-gate.png").unlink()

    report = build_offline_submission_readiness(root)

    document_check = next(
        check for check in report.checks if check.check_id == "submission_documents"
    )
    assert document_check.ready is False
    assert "06-ibm-bob-video-evidence-gate.png" in document_check.detail


def test_offline_submission_preflight_reports_missing_devpost_heading(tmp_path: Path) -> None:
    root = _prepared_root(tmp_path)
    draft = root / "devpost-submission.md"
    draft.write_text(
        draft.read_text(encoding="utf-8").replace("## How We Used Codex", "## Codex"),
        encoding="utf-8",
    )

    report = build_offline_submission_readiness(root)

    section_check = next(
        check for check in report.checks if check.check_id == "devpost_draft_sections"
    )
    assert section_check.ready is False
    assert "## How We Used Codex" in section_check.detail


def test_offline_submission_preflight_requires_recognized_root_license(tmp_path: Path) -> None:
    root = _prepared_root(tmp_path)
    (root / "LICENSE").unlink()

    report = build_offline_submission_readiness(root)

    assert report.offline_preparation_complete is False
    license_check = next(check for check in report.checks if check.check_id == "osi_license")
    assert license_check.ready is False
    assert license_check.detail == "missing or unrecognized root OSI license file"


def test_offline_submission_preflight_recognizes_agpl_license(tmp_path: Path) -> None:
    report = build_offline_submission_readiness(_prepared_root(tmp_path))

    license_check = next(check for check in report.checks if check.check_id == "osi_license")
    assert license_check.ready is True
    assert license_check.detail == "recognized license: AGPL-3.0"


def test_offline_submission_preflight_recognizes_mit_license(tmp_path: Path) -> None:
    root = _prepared_root(tmp_path)
    (root / "LICENSE").write_text(MIT_LICENSE_SAMPLE, encoding="utf-8")

    report = build_offline_submission_readiness(root)

    license_check = next(check for check in report.checks if check.check_id == "osi_license")
    assert license_check.ready is True
    assert license_check.detail == "recognized license: MIT"


def test_offline_submission_preflight_rejects_license_fragment(tmp_path: Path) -> None:
    root = _prepared_root(tmp_path)
    (root / "LICENSE").write_text(
        "Permission is hereby granted, free of charge\n"
        'THE SOFTWARE IS PROVIDED "AS IS"\n',
        encoding="utf-8",
    )

    report = build_offline_submission_readiness(root)

    license_check = next(check for check in report.checks if check.check_id == "osi_license")
    assert license_check.ready is False


def test_offline_submission_preflight_detects_private_media_in_source_tree(
    tmp_path: Path,
) -> None:
    root = _prepared_root(tmp_path)
    (root / "accidental.mp4").write_bytes(b"not a real video")

    report = build_offline_submission_readiness(root)

    private_check = next(
        check
        for check in report.checks
        if check.check_id == "no_private_media_in_public_source_tree"
    )
    assert private_check.ready is False
    assert "accidental.mp4" in private_check.detail


def test_offline_submission_preflight_allows_explicit_private_directory(
    tmp_path: Path,
) -> None:
    root = _prepared_root(tmp_path)
    private = root / "private-media/ride.mp4"
    private.parent.mkdir()
    private.write_bytes(b"not a real video")

    report = build_offline_submission_readiness(root)

    private_check = next(
        check
        for check in report.checks
        if check.check_id == "no_private_media_in_public_source_tree"
    )
    assert private_check.ready is True


def test_offline_submission_preflight_detects_secret_markers_in_public_text(
    tmp_path: Path,
) -> None:
    root = _prepared_root(tmp_path)
    source = root / "app/leak.py"
    source.parent.mkdir()
    source.write_text('key = "AIza' + "A" * 35 + '"\n', encoding="utf-8")

    report = build_offline_submission_readiness(root)

    secret_check = next(
        check
        for check in report.checks
        if check.check_id == "no_secret_markers_in_public_text"
    )
    assert secret_check.ready is False
    assert "app/leak.py:google_api_key" in secret_check.detail


def test_offline_submission_preflight_does_not_read_ignored_environment_file(
    tmp_path: Path,
) -> None:
    root = _prepared_root(tmp_path)
    (root / ".env").write_text('KEY="AIza' + "A" * 35 + '"\n', encoding="utf-8")

    report = build_offline_submission_readiness(root)

    secret_check = next(
        check
        for check in report.checks
        if check.check_id == "no_secret_markers_in_public_text"
    )
    assert secret_check.ready is True
