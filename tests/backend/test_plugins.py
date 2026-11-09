"""Unit tests for ``agent_backend.plugins``."""

import pytest

from agent_backend.bundle import load_bundle
from agent_backend.plugins import load_tool_router
from tests.backend.conftest import PLUGIN_SOURCE, make_bundle


def test_bundle_without_tools_has_no_router(agents_dir):
    assert load_tool_router(load_bundle(make_bundle(agents_dir, "a"))) is None


def test_plugin_router_is_loaded(agents_dir):
    router = load_tool_router(load_bundle(make_bundle(agents_dir, "a", plugin=PLUGIN_SOURCE)))
    assert [route.path for route in router.routes] == ["/ping-tool"]


def test_plugins_of_two_agents_do_not_collide(agents_dir):
    other = PLUGIN_SOURCE.replace("ping-tool", "other-tool")
    first = load_tool_router(load_bundle(make_bundle(agents_dir, "a", plugin=PLUGIN_SOURCE)))
    second = load_tool_router(load_bundle(make_bundle(agents_dir, "b", plugin=other)))
    assert first.routes[0].path == "/ping-tool"
    assert second.routes[0].path == "/other-tool"


def test_plugin_without_router_is_rejected(agents_dir):
    with pytest.raises(ImportError, match="router"):
        load_tool_router(load_bundle(make_bundle(agents_dir, "a", plugin="x = 1\n")))


def test_shared_plugin_is_used_by_every_agent_that_names_it(agents_dir):
    shared = agents_dir / "_tools" / "common"
    shared.mkdir(parents=True)
    (shared / "__init__.py").write_text(PLUGIN_SOURCE, encoding="utf-8")
    one = load_bundle(make_bundle(agents_dir, "one", agent_yaml="tools: common\n"))
    two = load_bundle(make_bundle(agents_dir, "two", agent_yaml="tools: common\n"))
    assert one.tools_dir == two.tools_dir == shared
    assert load_tool_router(one).routes[0].path == load_tool_router(two).routes[0].path == "/ping-tool"
