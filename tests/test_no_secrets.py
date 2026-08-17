from pathlib import Path


def test_gitignore_protects_private_material() -> None:
    ignored = Path(".gitignore").read_text()
    for entry in (
        ".env",
        ".DS_Store",
        "*.egg-info/",
        "*.gpx",
        "*.fit",
        "*.mp4",
        "*.mov",
        "*.lrv",
    ):
        assert entry in ignored
    assert "private-media/" in ignored


def test_example_has_no_secret_values() -> None:
    safe_defaults = {
        "BOX_MCP_NAME",
        "BOX_MCP_URL",
        "BOX_OAUTH_SCOPES",
        "GOOGLE_GENAI_USE_VERTEXAI",
        "AGENT_PLATFORM_LOCATION",
        "RIDE_ENV",
        "RIDE_UI_DEFAULT_LANGUAGE",
        "RIDE_WEB_HOST",
        "RIDE_WEB_MODE",
        "RIDE_WEB_PORT",
        }
    for line in Path(".env.example").read_text().splitlines():
        if "=" in line and line.split("=", 1)[0] not in safe_defaults:
            assert line.endswith("="), f"unexpected value in {line.split('=', 1)[0]}"
