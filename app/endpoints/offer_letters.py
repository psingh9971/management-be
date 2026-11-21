from typing import Optional
from uuid import UUID

from fastapi import APIRouter, Depends, Query, status
from fastapi.responses import HTMLResponse
from sqlalchemy.orm import Session

from app.core.deps import require_roles
from app.db.session import get_db
from app.documents.offer_letter import render_offer_letter
from app.models.offer_letter import OfferLetterStatus
from app.models.user import User, UserRole
from app.repositories import employee_repository, offer_letter_repository
from app.schemas.common import Page
from app.schemas.offer_letter import (
    OfferLetterConfirm,
    OfferLetterCreate,
    OfferLetterOut,
    OfferLetterUpdate,
    OfferLetterWithdraw,
)

# Offer letters disclose salary: admin or finance only
hr_user = require_roles(UserRole.ADMIN, UserRole.FINANCE)
router = APIRouter(tags=["offer letters"], dependencies=[Depends(hr_user)])


@router.post(
    "/employees/{employee_id}/offer-letters",
    response_model=OfferLetterOut,
    status_code=status.HTTP_201_CREATED,
)
def create_offer_letter(
    employee_id: UUID,
    payload: OfferLetterCreate,
    user: User = Depends(hr_user),
    db: Session = Depends(get_db),
):
    """Issue a provisional offer letter. The salary breakdown comes from the employee's current
    salary assignment; the joining date is only tentative until the letter is confirmed."""
    return offer_letter_repository.create_letter(db, employee_id, payload, user)


@router.get("/employees/{employee_id}/offer-letters", response_model=Page[OfferLetterOut])
def list_employee_offer_letters(
    employee_id: UUID,
    skip: int = Query(0, ge=0),
    limit: int = Query(50, ge=1, le=200),
    db: Session = Depends(get_db),
):
    employee_repository.require_employee(db, employee_id)
    items, total = offer_letter_repository.list_letters(db, employee_id=employee_id, skip=skip, limit=limit)
    return Page(items=items, total=total, skip=skip, limit=limit)


@router.get("/offer-letters", response_model=Page[OfferLetterOut])
def list_offer_letters(
    status_: Optional[OfferLetterStatus] = Query(None, alias="status"),
    skip: int = Query(0, ge=0),
    limit: int = Query(50, ge=1, le=200),
    db: Session = Depends(get_db),
):
    items, total = offer_letter_repository.list_letters(db, status=status_, skip=skip, limit=limit)
    return Page(items=items, total=total, skip=skip, limit=limit)


@router.get("/offer-letters/{letter_id}", response_model=OfferLetterOut)
def get_offer_letter(letter_id: UUID, db: Session = Depends(get_db)):
    return offer_letter_repository.get_letter(db, letter_id)


@router.patch("/offer-letters/{letter_id}", response_model=OfferLetterOut)
def update_offer_letter(letter_id: UUID, payload: OfferLetterUpdate, db: Session = Depends(get_db)):
    """Edit a provisional letter. The salary is re-read from the current salary assignment,
    so change the assignment first if the offered salary changes."""
    return offer_letter_repository.update_letter(db, letter_id, payload)


@router.post("/offer-letters/{letter_id}/confirm", response_model=OfferLetterOut)
def confirm_offer_letter(
    letter_id: UUID,
    payload: OfferLetterConfirm,
    user: User = Depends(hr_user),
    db: Session = Depends(get_db),
):
    """Confirm the joining date. Also sets the employee's date_of_joining unless told not to."""
    return offer_letter_repository.confirm_letter(db, letter_id, payload, user)


@router.post("/offer-letters/{letter_id}/withdraw", response_model=OfferLetterOut)
def withdraw_offer_letter(letter_id: UUID, payload: OfferLetterWithdraw, db: Session = Depends(get_db)):
    return offer_letter_repository.withdraw_letter(db, letter_id, payload.reason)


@router.get("/offer-letters/{letter_id}/document", response_class=HTMLResponse)
def offer_letter_document(letter_id: UUID, db: Session = Depends(get_db)):
    """The letter as a printable HTML page (use the browser's Print -> Save as PDF).
    Provisional letters show the joining date as tentative; confirmed ones show the final date."""
    return HTMLResponse(render_offer_letter(offer_letter_repository.get_letter(db, letter_id)))
