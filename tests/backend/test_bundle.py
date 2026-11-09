"""Unit tests for ``agent_backend.bundle``."""

import pytest

from agent_backend.bundle import discover_bundles, load_bundle
from tests.backend.conftest import make_bundle


def test_discovery_ignores_folders_without_a_graph(agents_dir):
    make_bundle(agents_dir, "alpha")
    (agents_dir / "half_copied").mkdir()
    assert list(discover_bundles(agents_dir)) == ["alpha"]


def test_discovery_of_missing_directory_is_empty(tmp_path):
    assert discover_bundles(tmp_path / "nope") == {}


def test_agent_yaml_is_optional_and_env_prefix_defaults_to_slug(agents_dir):
    bundle = load_bundle(make_bundle(agents_dir, "sam_text"))
    assert bundle.config.ghl is None
    assert bundle.env_prefix == "SAM_TEXT"


def test_ghl_section_is_parsed(agents_dir):
    yaml_text = "ghl:\n  debounce_seconds: 5\n  token_envs: [X_TOKEN]\n"
    bundle = load_bundle(make_bundle(agents_dir, "a", agent_yaml=yaml_text))
    assert bundle.config.ghl.debounce_seconds == 5
    assert bundle.config.ghl.token_envs == ("X_TOKEN",)


def test_unknown_agent_yaml_key_is_rejected(agents_dir):
    with pytest.raises(ValueError, match="agent.yaml"):
        load_bundle(make_bundle(agents_dir, "a", agent_yaml="gh1: {}\n"))


def test_missing_graph_raises(agents_dir):
    (agents_dir / "empty").mkdir()
    with pytest.raises(FileNotFoundError):
        load_bundle(agents_dir / "empty")
