"""FastAPI apps wrapping each tool plugin under the legacy ``/api/v1`` prefix, for tests."""

from desk import router as desk_router
from fastapi import FastAPI
from surrogacy import router as surrogacy_router

desk_app = FastAPI(title="family_aims (test)")
desk_app.include_router(desk_router, prefix="/api/v1")

surrogacy_app = FastAPI(title="surrogacy (test)")
surrogacy_app.include_router(surrogacy_router, prefix="/api/v1")

