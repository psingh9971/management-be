"""Row-level tenant isolation, applied automatically to every ORM query.

Once `set_tenant(db, tenant_id)` has been called on a session (done by get_current_user for
authenticated requests, and by the webhook for device punches):

* every ORM SELECT / UPDATE / DELETE that touches a TenantMixin model gets
  `WHERE <table>.tenant_id = :tenant_id` added, including joins, relationship loads and db.get();
* every new TenantMixin object gets tenant_id filled in on flush.

A session with no tenant set is unfiltered (used for login and user lookup during auth), but it
refuses to insert TenantMixin rows, so data can never be written without an owner.

Core statements built with `insert()` (e.g. Postgres ON CONFLICT upserts) bypass the ORM unit
of work, so they must set tenant_id explicitly.
"""
import uuid
from typing import Optional

from sqlalchemy import event
from sqlalchemy.orm import ORMExecuteState, Session, with_loader_criteria

from app.db.base import TenantMixin

_TENANT_KEY = "tenant_id"
# Per-statement escape hatch: select(...).execution_options(skip_tenant_filter=True)
SKIP_TENANT_FILTER = "skip_tenant_filter"


def set_tenant(db: Session, tenant_id: uuid.UUID) -> None:
    db.info[_TENANT_KEY] = tenant_id


def current_tenant_id(db: Session) -> Optional[uuid.UUID]:
    return db.info.get(_TENANT_KEY)


@event.listens_for(Session, "do_orm_execute")
def _filter_by_tenant(state: ORMExecuteState) -> None:
    tenant_id = state.session.info.get(_TENANT_KEY)
    if tenant_id is None or state.execution_options.get(SKIP_TENANT_FILTER):
        return
    if not (state.is_select or state.is_update or state.is_delete):
        return
    # Column / relationship lazy loads come from rows that were already filtered
    if state.is_column_load or state.is_relationship_load:
        return
    state.statement = state.statement.options(
        with_loader_criteria(
            TenantMixin,
            lambda cls: cls.tenant_id == tenant_id,
            include_aliases=True,
        )
    )


@event.listens_for(Session, "before_flush")
def _stamp_tenant(session: Session, flush_context, instances) -> None:
    tenant_id = session.info.get(_TENANT_KEY)
    for obj in session.new:
        if not isinstance(obj, TenantMixin):
            continue
        if obj.tenant_id is None:
            if tenant_id is None:
                raise RuntimeError(
                    f"Cannot insert {type(obj).__name__} without a tenant: call set_tenant() first"
                )
            obj.tenant_id = tenant_id
        elif tenant_id is not None and obj.tenant_id != tenant_id:
            raise RuntimeError(f"Refusing to insert {type(obj).__name__} into another tenant")
