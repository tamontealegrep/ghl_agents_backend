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


@pytest.fixture
def clean_shared_import():
    """Leaves ``sys.path`` and the ``shared`` package exactly as they were."""
    import sys

    saved_path = list(sys.path)
    saved_modules = {k: v for k, v in sys.modules.items() if k == "shared" or k.startswith("shared.")}
    for name in saved_modules:
        del sys.modules[name]
    yield
    sys.path[:] = saved_path
    for name in [k for k in sys.modules if k == "shared" or k.startswith("shared.")]:
        del sys.modules[name]
    sys.modules.update(saved_modules)


def _make_company_shared(company_root, **modules: str) -> None:
    tools = company_root / "shared" / "tools"
    tools.mkdir(parents=True)
    (company_root / "shared" / "__init__.py").write_text("", encoding="utf-8")
    (tools / "__init__.py").write_text("", encoding="utf-8")
    for name, source in modules.items():
        (tools / f"{name}.py").write_text(source, encoding="utf-8")


def test_a_plugin_can_import_from_the_company_shared_tools(agents_dir, clean_shared_import):
    _make_company_shared(agents_dir.parent, greeting="ROUTE = '/from-shared'\n")
    plugin = PLUGIN_SOURCE.replace('"/ping-tool"', "ROUTE").replace(
        "from fastapi import APIRouter",
        "from fastapi import APIRouter\nfrom shared.tools.greeting import ROUTE",
    )

    router = load_tool_router(load_bundle(make_bundle(agents_dir, "a", plugin=plugin)))

    assert [route.path for route in router.routes] == ["/from-shared"]


def test_two_business_units_of_one_company_share_the_same_module(agents_dir, clean_shared_import):
    _make_company_shared(agents_dir.parent, counter="CALLS = []\n")
    unit = "from fastapi import APIRouter\nfrom shared.tools import counter\nrouter = APIRouter()\ncounter.CALLS.append('{name}')\n"

    load_tool_router(load_bundle(make_bundle(agents_dir, "unit_a", plugin=unit.format(name="a"))))
    load_tool_router(load_bundle(make_bundle(agents_dir, "unit_b", plugin=unit.format(name="b"))))

    import shared.tools.counter as counter

    assert counter.CALLS == ["a", "b"]


def test_a_company_without_a_shared_folder_changes_nothing(agents_dir, clean_shared_import):
    import sys

    before = list(sys.path)
    load_tool_router(load_bundle(make_bundle(agents_dir, "a", plugin=PLUGIN_SOURCE)))
    assert sys.path == before


def test_every_company_ships_an_importable_shared_tools_package():
    from pathlib import Path

    companies = Path(__file__).resolve().parents[2] / "companies"
    for company in ("_template", "family_aims", "babynova"):
        assert (companies / company / "shared" / "__init__.py").is_file(), company
        assert (companies / company / "shared" / "tools" / "__init__.py").is_file(), company
