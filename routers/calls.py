from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from database import get_db
from models import User, Call
from schemas.call import CallResponse
from services.auth import get_current_user

router = APIRouter(prefix="/api/v1/calls", tags=["Calls"])

@router.post("/start")
def start_call(
    receiver_id: int,
    call_type: str = "video",
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    call = Call(
        caller_id=current_user.id,
        receiver_id=receiver_id,
        call_type=call_type,
        status="pending"
    )

    db.add(call)
    db.commit()
    db.refresh(call)

    return {
        "call_id": call.id,
        "status": "pending"
    }

@router.patch("/{call_id}/accept")
def accept_call(
    call_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    call = db.query(Call).filter(Call.id == call_id).first()

    if not call:
        raise HTTPException(404, "Call không tồn tại")

    call.status = "accepted"
    call.started_at = datetime.utcnow()

    db.commit()

    return {"message": "Đã accept"}

@router.patch("/{call_id}/reject")
def reject_call(
    call_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    call = db.query(Call).filter(Call.id == call_id).first()

    if not call:
        raise HTTPException(404, "Call không tồn tại")

    call.status = "rejected"
    call.ended_at = datetime.utcnow()

    db.commit()

    return {"message": "Đã reject"}

@router.patch("/{call_id}/end")
def end_call(
    call_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    call = db.query(Call).filter(Call.id == call_id).first()

    if not call:
        raise HTTPException(404, "Call không tồn tại")

    call.status = "ended"
    call.ended_at = datetime.utcnow()

    if call.started_at:
        call.duration = int(
            (call.ended_at - call.started_at).total_seconds()
        )

    db.commit()

    return {"message": "Đã kết thúc"}

@router.get("/history", response_model=list[CallResponse])
def call_history(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    return db.query(Call).filter(
        (Call.caller_id == current_user.id) |
        (Call.receiver_id == current_user.id)
    ).order_by(Call.started_at.desc()).all()

@router.get("/missed")
def missed_calls(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    return db.query(Call).filter(
        Call.receiver_id == current_user.id,
        Call.status == "missed"
    ).all()