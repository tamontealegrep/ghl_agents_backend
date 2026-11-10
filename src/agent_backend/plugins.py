"""Loads an agent's own tool routes from its bundle without touching the backend.

Plugin contract: ``<bundle>/tools/__init__.py`` (or ``router.py``) exposes a
module-level ``router``, a ``fastapi.APIRouter``. The backend mounts it at
``/agents/<company>/tools`` (``/agents/<slug>/tools`` when ``COMPANY`` is unset), which is
where the agents' compiled tool calls land.
Relative imports inside the ``tools`` folder work as in any package.

A company can keep code that several of its business units share in
``<company>/shared/tools/`` (next to the ``bundles`` folder). When
``<company>/shared/__init__.py`` exists, the company folder is put on
``sys.path`` so any plugin can ``from shared.tools.<module> import ...``.

Bundles are trusted code supplied by the operator, like the image itself.
"""

from __future__ import annotations

import importlib.util
import sys
from types import ModuleType

from fastapi import APIRouter

from agent_backend.bundle import AgentBundle

_ENTRYPOINTS = ("__init__.py", "router.py")


def _module_name(bundle: AgentBundle) -> str:
    """Builds a sys.modules name that cannot collide between agents.

    Args:
        bundle: Bundle whose plugin is being loaded.

    Returns:
        A unique, import-safe module name.
    """
    return f"agent_tools_{bundle.slug}"


def _import_plugin(bundle: AgentBundle) -> ModuleType:
    """Imports the bundle's tools package, replacing any previous version.

    Args:
        bundle: Bundle with a ``tools`` folder.

    Returns:
        The freshly imported module.

    Raises:
        ImportError: If the folder has no entrypoint or cannot be imported.
    """
    entry = next(
        (bundle.tools_dir / name for name in _ENTRYPOINTS if (bundle.tools_dir / name).is_file()), None
    )
    if entry is None:
        raise ImportError(f"{bundle.tools_dir} needs one of {', '.join(_ENTRYPOINTS)}")

    name = _module_name(bundle)
    for loaded in [m for m in sys.modules if m == name or m.startswith(f"{name}.")]:
        del sys.modules[loaded]

    spec = importlib.util.spec_from_file_location(
        name, entry, submodule_search_locations=[str(bundle.tools_dir)]
    )
    if spec is None or spec.loader is None:
        raise ImportError(f"Cannot import tool plugin from {entry}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


def _expose_company_shared(bundle: AgentBundle) -> None:
    """Makes ``<company>/shared`` importable as the top-level package ``shared``.

    One backend serves one company, so the name is unambiguous. Nothing happens when
    the company has no ``shared/__init__.py``.

    Args:
        bundle: Bundle about to load its plugin; its folder sits in ``<company>/bundles``.
    """
    company_root = bundle.root.parent.parent
    if (company_root / "shared" / "__init__.py").is_file() and str(company_root) not in sys.path:
        sys.path.insert(0, str(company_root))


def load_tool_router(bundle: AgentBundle) -> APIRouter | None:
    """Loads the agent's tool router, if the bundle ships one.

    Args:
        bundle: Bundle to inspect.

    Returns:
        The plugin's ``router``, or ``None`` when the bundle has no ``tools`` folder.

    Raises:
        ImportError: If the plugin does not expose a ``router`` ``APIRouter``.
    """
    if not bundle.tools_dir.is_dir():
        return None
    _expose_company_shared(bundle)
    router = getattr(_import_plugin(bundle), "router", None)
    if not isinstance(router, APIRouter):
        raise ImportError(f"{bundle.tools_dir} must expose a module-level `router: APIRouter`")
    return router
