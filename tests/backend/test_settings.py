"""Unit tests for ``agent_backend.settings``."""

from pathlib import Path

from agent_backend.settings import Settings


def test_defaults_when_environment_is_empty():
    settings = Settings.from_env({})
    assert (settings.host, settings.port) == ("127.0.0.1", 8010)
    assert settings.admin_token is None
    assert settings.agents_dir == Path("bundles").resolve()


def test_wildcard_host_is_called_through_loopback():
    settings = Settings.from_env({"HOST": "0.0.0.0", "PORT": "9000"})
    assert settings.self_base_url == "http://127.0.0.1:9000"


def test_empty_admin_token_means_open_admin():
    assert Settings.from_env({"ADMIN_TOKEN": ""}).admin_token is None
