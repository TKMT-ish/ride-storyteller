from pathlib import Path

from app.submission import build_offline_submission_readiness

REQUIRED_DOCUMENTS = (
    "README.md",
    "devpost-submission.md",
    "docs/ui-localization.md",
    "docs/google-story-copy.md",
    "docs/agent-platform-deployment-preflight.md",
    "docs/public-demo-hosting.md",
    "docs/cloud-run-public-demo.md",
    "docs/submission/project-writeup-en.md",
    "docs/submission/architecture.md",
    "docs/submission/demo-script-en.md",
    "docs/submission/demo-subtitles-en.srt",
    "docs/submission/screenshot-plan.md",
    "docs/submission/ibm-bob-evidence.md",
    "docs/submission/ibm-bob-review-sanitized.md",
    "docs/submission/judging-alignment.md",
    "docs/submission/official-rules-audit.md",
    "docs/submission/technical-evidence.md",
    "docs/submission/test-evidence.md",
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


def _prepared_root(root: Path) -> Path:
    for relative in REQUIRED_DOCUMENTS:
        path = root / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("prepared", encoding="utf-8")
    (root / ".gitignore").write_text(
        ".env\n*.gpx\n*.fit\n*.mp4\n*.mov\n*.lrv\nprivate-media/\n",
        encoding="utf-8",
    )
    (root / "LICENSE").write_text(MIT_LICENSE_SAMPLE, encoding="utf-8")
    return root


def test_offline_submission_preflight_passes_complete_local_preparation(tmp_path: Path) -> None:
    report = build_offline_submission_readiness(_prepared_root(tmp_path))

    assert report.offline_preparation_complete is True
    assert report.to_dict()["submission_ready"] is False
    assert report.external_gates
    assert report.media_gates


def test_offline_submission_preflight_reports_missing_documents(tmp_path: Path) -> None:
    root = _prepared_root(tmp_path)
    (root / "docs/submission/demo-script-en.md").unlink()

    report = build_offline_submission_readiness(root)

    assert report.offline_preparation_complete is False
    document_check = next(
        check for check in report.checks if check.check_id == "submission_documents"
    )
    assert "demo-script-en.md" in document_check.detail


def test_offline_submission_preflight_requires_recognized_root_license(tmp_path: Path) -> None:
    root = _prepared_root(tmp_path)
    (root / "LICENSE").unlink()

    report = build_offline_submission_readiness(root)

    assert report.offline_preparation_complete is False
    license_check = next(check for check in report.checks if check.check_id == "osi_license")
    assert license_check.ready is False
    assert license_check.detail == "missing or unrecognized root OSI license file"


def test_offline_submission_preflight_recognizes_mit_license(tmp_path: Path) -> None:
    report = build_offline_submission_readiness(_prepared_root(tmp_path))

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
