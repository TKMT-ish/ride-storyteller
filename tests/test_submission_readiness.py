from pathlib import Path

from app.submission import build_offline_submission_readiness

REQUIRED_DOCUMENTS = (
    "README.md",
    "docs/ui-localization.md",
    "docs/google-story-copy.md",
    "docs/agent-platform-deployment-preflight.md",
    "docs/public-demo-hosting.md",
    "docs/submission/project-writeup-en.md",
    "docs/submission/architecture.md",
    "docs/submission/demo-script-en.md",
    "docs/submission/demo-subtitles-en.srt",
    "docs/submission/screenshot-plan.md",
    "docs/submission/ibm-bob-evidence.md",
    "docs/submission/technical-evidence.md",
    "docs/submission/test-evidence.md",
)


def _prepared_root(root: Path) -> Path:
    for relative in REQUIRED_DOCUMENTS:
        path = root / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("prepared", encoding="utf-8")
    (root / ".gitignore").write_text(
        ".env\n*.gpx\n*.fit\n*.mp4\n*.mov\n*.lrv\nprivate-media/\n",
        encoding="utf-8",
    )
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
