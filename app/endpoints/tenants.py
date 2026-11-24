from typing import Optional

from fastapi import APIRouter, Depends, Header, HTTPException, Query, status
from sqlalchemy.orm import Session

from app.db.session import get_db
from app.repositories import tenant_repository
from app.schemas.tenant import TenantPublic

router = APIRouter(prefix="/tenants", tags=["tenants"])


@router.get("/current", response_model=TenantPublic)
def current_tenant(
    db: Session = Depends(get_db),
    x_tenant_host: Optional[str] = Header(
        None, description="The frontend's host, e.g. window.location.host -> 'demo.example.com'"
    ),
    origin: Optional[str] = Header(None),
    host: Optional[str] = Header(None),
    host_override: Optional[str] = Query(None, alias="host", description="Fallback when headers can't be set"),
):
    """Public: resolve the tenant from the frontend's subdomain so the login page can show
    its name and send its id with the login request.

    The host is read from, in order: the `X-Tenant-Host` header, the `?host=` query param,
    the `Origin` header (set by the browser on cross-origin calls), then `Host`.
    """
    for candidate in (x_tenant_host, host_override, origin, host):
        if not candidate:
            continue
        subdomain = tenant_repository.subdomain_from_host(candidate)
        if subdomain:
            break
    else:
        print("sdsdsd")
        print(x_tenant_host)
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Could not determine tenant subdomain from host")

    tenant = tenant_repository.get_active_by_domain(db, subdomain)
    if tenant is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f"No tenant found for '{subdomain}'")
    return tenant
