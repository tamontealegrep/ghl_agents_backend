# shared/tools

Code that **several business units of this company** use. A unit (a folder in `bundles/_tools/<unit>/`, such as
`desk` or `surrogacy`) must not copy a module its sibling units already need: put it here and import it.

```python
# bundles/_tools/<unit>/services/anything.py
from shared.tools.my_module import my_function
```

How it works:

- `shared/` sits next to `bundles/` and is mounted in the container at `/app/shared` (see `docker-compose.yml`).
- The backend puts the company folder on `sys.path` when `shared/__init__.py` exists, so `shared` is a top-level package.
- It is plain Python with no routes of its own: a unit's `router` decides which endpoints it exposes.

Layout (create only what you need; the folders are there so every company looks the same):

| Folder | Holds |
|---|---|
| `services/` | Pure business rules shared by units. |
| `schemas/` | Pydantic models shared by units. |
| `utils/` | Small helpers. |
| `config/` | Shared data files (YAML/JSON), read by path from `Path(__file__)`. |
| `templates/` | Shared templates (e.g. email), read by path. |

There is no `api/` here: routes belong to each unit's `router`, which calls the shared function.

Rules:

1. Only what two or more units really share. Anything that only one unit uses stays in that unit.
2. Code every company needs belongs in the backend (`src/agent_backend/`), not here.
3. A module here never imports from a unit (`bundles/_tools/<unit>`); units depend on `shared`, never the other way.
4. Environment variables are read where they are used and documented in this company's `env.example`.
