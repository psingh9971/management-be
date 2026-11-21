from fastapi import APIRouter, Depends, FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from app.core.config import settings
from app.core.deps import get_current_user
from app.endpoints import (
    attendance,
    auth,
    employees,
    holidays,
    leave_types,
    leaves,
    offer_letters,
    payroll,
    users,
    week_offs,
    webhooks,
)
from app.repositories.errors import DomainError

API_PREFIX = "/api"

# Schema is managed by Alembic: run `alembic upgrade head` before starting the app.
app = FastAPI(
    title=settings.APP_NAME,
    docs_url=f"{API_PREFIX}/docs",
    redoc_url=f"{API_PREFIX}/redoc",
    openapi_url=f"{API_PREFIX}/openapi.json",
    swagger_ui_oauth2_redirect_url=f"{API_PREFIX}/docs/oauth2-redirect",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.exception_handler(DomainError)
def handle_domain_error(_: Request, exc: DomainError):
    return JSONResponse(status_code=exc.status_code, content={"detail": exc.detail})


authenticated = [Depends(get_current_user)]

# Every route lives under /api, e.g. /api/auth/login
api = APIRouter(prefix=API_PREFIX)

# Public
api.include_router(auth.router)
# Authenticated via X-Webhook-Secret (devices can't log in with a user account)
api.include_router(webhooks.router)
# JWT-protected (some routes additionally require the admin role)
api.include_router(employees.router, dependencies=authenticated)
api.include_router(attendance.router, dependencies=authenticated)
api.include_router(leaves.router, dependencies=authenticated)
api.include_router(leave_types.router, dependencies=authenticated)
api.include_router(holidays.router, dependencies=authenticated)
api.include_router(week_offs.router, dependencies=authenticated)
api.include_router(payroll.router, dependencies=authenticated)  # admin / finance only
api.include_router(offer_letters.router, dependencies=authenticated)  # admin / finance only
api.include_router(users.router)  # super admin only (enforced in the router)


@api.get("/health", tags=["health"])
def health():
    return {"status": "ok"}


app.include_router(api)
