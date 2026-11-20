from fastapi import Depends, FastAPI, Request
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
    payroll,
    users,
    week_offs,
    webhooks,
)
from app.repositories.errors import DomainError

# Schema is managed by Alembic: run `alembic upgrade head` before starting the app.
app = FastAPI(title=settings.APP_NAME)


@app.exception_handler(DomainError)
def handle_domain_error(_: Request, exc: DomainError):
    return JSONResponse(status_code=exc.status_code, content={"detail": exc.detail})


authenticated = [Depends(get_current_user)]

# Public
app.include_router(auth.router)
# Authenticated via X-Webhook-Secret (devices can't log in with a user account)
app.include_router(webhooks.router)
# JWT-protected (some routes additionally require the admin role)
app.include_router(employees.router, dependencies=authenticated)
app.include_router(attendance.router, dependencies=authenticated)
app.include_router(leaves.router, dependencies=authenticated)
app.include_router(leave_types.router, dependencies=authenticated)
app.include_router(holidays.router, dependencies=authenticated)
app.include_router(week_offs.router, dependencies=authenticated)
app.include_router(payroll.router, dependencies=authenticated)  # admin / finance only
app.include_router(users.router)  # super admin only (enforced in the router)


@app.get("/health", tags=["health"])
def health():
    return {"status": "ok"}
