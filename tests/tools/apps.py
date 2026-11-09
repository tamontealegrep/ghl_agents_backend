"""FastAPI apps wrapping each tool plugin under the legacy ``/api/v1`` prefix, for tests."""

from fastapi import FastAPI

from family_aims import router as family_aims_router
from babynova_surrogacy import router as babynova_surrogacy_router

family_aims_app = FastAPI(title="family_aims (test)")
family_aims_app.include_router(family_aims_router, prefix="/api/v1")

babynova_surrogacy_app = FastAPI(title="babynova_surrogacy (test)")
babynova_surrogacy_app.include_router(babynova_surrogacy_router, prefix="/api/v1")

