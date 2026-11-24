from uuid import UUID

from pydantic import BaseModel, ConfigDict


class TenantPublic(BaseModel):
    """What an unauthenticated frontend may know about the tenant it is served for."""

    model_config = ConfigDict(from_attributes=True)

    id: UUID
    name: str
    slug: str
    domain: str
