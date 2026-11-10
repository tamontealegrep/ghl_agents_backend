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

Rules:

1. Only what two or more units really share. Anything that only one unit uses stays in that unit.
2. Code every company needs belongs in the backend (`src/agent_backend/`), not here.
3. A module here never imports from a unit (`bundles/_tools/<unit>`); units depend on `shared`, never the other way.
4. Environment variables are read where they are used and documented in this company's `env.example`.
