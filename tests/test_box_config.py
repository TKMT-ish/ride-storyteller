from app.mcp import BoxMcpSettings, preflight_box_mcp


def test_preflight_reports_missing_oauth_values_without_showing_them() -> None:
    result = preflight_box_mcp(
        BoxMcpSettings("https://mcp.box.com", "box-remote-mcp", "", "", "", "Content Actions")
    )
    assert result.ready is False
    assert result.missing == ("BOX_CLIENT_ID", "BOX_CLIENT_SECRET", "BOX_OAUTH_REDIRECT_URI")
    assert result.errors == ()


def test_preflight_accepts_complete_remote_box_configuration() -> None:
    result = preflight_box_mcp(
        BoxMcpSettings(
            "https://mcp.box.com",
            "box-remote-mcp",
            "client-id",
            "not-a-real-secret",
            "https://ride-storyteller.example.com/oauth/box/callback",
            "Content Actions",
        )
    )
    assert result.ready is True


def test_preflight_accepts_localhost_http_redirect_for_local_development() -> None:
    result = preflight_box_mcp(
        BoxMcpSettings(
            "https://mcp.box.com",
            "box-remote-mcp",
            "client-id",
            "not-a-real-secret",
            "http://localhost:8765/oauth/callback",
            "Content Actions",
        )
    )
    assert result.ready is True


def test_preflight_rejects_legacy_or_insecure_configuration() -> None:
    result = preflight_box_mcp(
        BoxMcpSettings(
            "http://localhost:8000",
            "old-server",
            "client-id",
            "not-a-real-secret",
            "http://example.com/callback",
            "",
        )
    )
    assert result.ready is False
    assert len(result.errors) == 4


def test_settings_load_ignored_local_environment_without_exposing_values(
    monkeypatch, tmp_path
) -> None:  # type: ignore[no-untyped-def]
    monkeypatch.chdir(tmp_path)
    (tmp_path / ".env").write_text(
        "BOX_CLIENT_ID=local-client\n"
        "BOX_CLIENT_SECRET=local-secret\n"
        "BOX_OAUTH_REDIRECT_URI=http://localhost:8765/oauth/callback\n"
    )

    settings = BoxMcpSettings.from_environment()
    result = preflight_box_mcp(settings)

    assert result.ready is True
    assert result.to_dict() == {"ready": True, "missing": [], "errors": []}
    assert "local-secret" not in str(result.to_dict())


def test_process_environment_takes_precedence_over_local_environment(
    monkeypatch, tmp_path
) -> None:  # type: ignore[no-untyped-def]
    monkeypatch.chdir(tmp_path)
    (tmp_path / ".env").write_text("BOX_CLIENT_ID=local-client\n")
    monkeypatch.setenv("BOX_CLIENT_ID", "process-client")

    settings = BoxMcpSettings.from_environment()

    assert settings.client_id == "process-client"
