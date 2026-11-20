import hmac
from typing import Optional

from fastapi import APIRouter, Depends, Header, HTTPException, Response, status
from sqlalchemy.orm import Session

from app.core.config import settings
from app.db.session import get_db
from app.repositories import attendance_repository, employee_repository
from app.schemas.attendance import PunchWebhookIn, PunchWebhookResult

router = APIRouter(prefix="/webhooks", tags=["webhooks"])


def verify_webhook_secret(x_webhook_secret: Optional[str] = Header(None)) -> None:
    if not settings.WEBHOOK_SECRET:
        return
    if not x_webhook_secret or not hmac.compare_digest(x_webhook_secret, settings.WEBHOOK_SECRET):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid webhook secret")


@router.post(
    "/attendance/punch",
    response_model=PunchWebhookResult,
    status_code=status.HTTP_201_CREATED,
    dependencies=[Depends(verify_webhook_secret)],
)
def incoming_punch(payload: PunchWebhookIn, response: Response, db: Session = Depends(get_db)):
    employee = employee_repository.get_employee_by_code(db, payload.employee_code)
    if not employee:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"No employee with code '{payload.employee_code}'",
        )
    if not employee.is_active:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="Employee is inactive")

    punch, created = attendance_repository.record_punch(
        db,
        employee=employee,
        punch_time=payload.punch_time,
        punch_type=payload.punch_type,
        device_id=payload.device_id,
        raw_payload=payload.model_dump(mode="json"),
    )
    if not created:
        response.status_code = status.HTTP_200_OK
    return PunchWebhookResult(status="created" if created else "duplicate", punch=punch)
