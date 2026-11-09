"""Fixtures that build throwaway agent bundles on disk."""

from __future__ import annotations

from pathlib import Path
from textwrap import dedent

import pytest

from agent_backend.settings import Settings

PLUGIN_SOURCE = dedent(
    """
    from fastapi import APIRouter

    router = APIRouter()


    @router.post("/ping-tool")
    def ping_tool() -> dict:
        return {"pong": True}
    """
)


def make_bundle(root: Path, slug: str, *, agent_yaml: str | None = None, plugin: str | None = None) -> Path:
    """Creates a minimal bundle folder under ``root``.

    Args:
        root: The agents directory.
        slug: Bundle folder name.
        agent_yaml: Optional contents of ``agent.yaml``.
        plugin: Optional source of ``tools/__init__.py``.

    Returns:
        The bundle folder.
    """
    bundle = root / slug
    bundle.mkdir(parents=True)
    (bundle / "graph.json").write_text("{}", encoding="utf-8")
    if agent_yaml is not None:
        (bundle / "agent.yaml").write_text(agent_yaml, encoding="utf-8")
    if plugin is not None:
        (bundle / "tools").mkdir()
        (bundle / "tools" / "__init__.py").write_text(plugin, encoding="utf-8")
    return bundle


@pytest.fixture
def agents_dir(tmp_path: Path) -> Path:
    """Empty agents directory for one test.

    Args:
        tmp_path: pytest temporary directory.

    Returns:
        A fresh, existing directory.
    """
    path = tmp_path / "agents"
    path.mkdir()
    return path


@pytest.fixture
def settings(agents_dir: Path) -> Settings:
    """Settings pointing at the test agents directory.

    Args:
        agents_dir: Directory fixture.

    Returns:
        Settings with no admin token.
    """
    return Settings(host="127.0.0.1", port=8010, agents_dir=agents_dir, admin_token=None)
