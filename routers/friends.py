from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from sqlalchemy import or_, and_

from database import get_db
from models import User, FriendRequest
from services.auth import get_current_user, is_blocked
from services.notification import create_notification

router = APIRouter(prefix="/api/v1/friends", tags=["Friends"])

@router.post("/request/{user_id}")
async def send_friend_request(
    user_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    if is_blocked(db, current_user.id, user_id):
        raise HTTPException(403, "Không thể kết bạn (đã block)")

    if user_id == current_user.id:
        raise HTTPException(400, "Không thể kết bạn với chính mình")

    user = db.query(User).filter(User.id == user_id).first()
    if not user:
        raise HTTPException(404, "User không tồn tại")

    existing = db.query(FriendRequest).filter(
        or_(
            and_(FriendRequest.sender_id == current_user.id, FriendRequest.receiver_id == user_id),
            and_(FriendRequest.sender_id == user_id, FriendRequest.receiver_id == current_user.id)
        )
    ).first()

    if existing:
        raise HTTPException(400, "Đã gửi hoặc đã là bạn")

    fr = FriendRequest(
        sender_id=current_user.id,
        receiver_id=user_id
    )

    db.add(fr)
    db.commit()

    # 🔥 notification
    await create_notification(
        db=db,
        user_id=user_id,
        actor_id=current_user.id,
        type="friend_request",
        message=f"{current_user.full_name} đã gửi lời mời kết bạn"
    )

    return {"message": "Đã gửi lời mời"}

@router.post("/accept/{request_id}")
async def accept_request(
    request_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    fr = db.query(FriendRequest).filter(
        FriendRequest.id == request_id,
        FriendRequest.receiver_id == current_user.id
    ).first()

    if not fr:
        raise HTTPException(404, "Không tìm thấy lời mời")

    fr.status = "accepted"
    db.commit()

    await create_notification(
        db=db,
        user_id=fr.sender_id,
        actor_id=current_user.id,
        type="friend_accept",
        message=f"{current_user.full_name} đã chấp nhận lời mời kết bạn"
    )

    return {"message": "Đã chấp nhận"}

@router.post("/reject/{request_id}")
def reject_request(
    request_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    fr = db.query(FriendRequest).filter(
        FriendRequest.id == request_id,
        FriendRequest.receiver_id == current_user.id
    ).first()

    if not fr:
        raise HTTPException(404, "Không tìm thấy")

    fr.status = "rejected"
    db.commit()

    return {"message": "Đã từ chối"}

@router.delete("/cancel/{request_id}")
def cancel_request(
    request_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    fr = db.query(FriendRequest).filter(
        FriendRequest.id == request_id,
        FriendRequest.sender_id == current_user.id
    ).first()

    if not fr:
        raise HTTPException(404, "Không tìm thấy")

    db.delete(fr)
    db.commit()

    return {"message": "Đã hủy lời mời"}

@router.get("/requests")
def get_requests(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    return db.query(FriendRequest).filter(
        FriendRequest.receiver_id == current_user.id,
        FriendRequest.status == "pending"
    ).all()

@router.get("/list")
def get_friends(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    friends = db.query(FriendRequest).filter(
        or_(
            FriendRequest.sender_id == current_user.id,
            FriendRequest.receiver_id == current_user.id
        ),
        FriendRequest.status == "accepted"
    ).all()

    result = []

    for fr in friends:
        friend_id = fr.receiver_id if fr.sender_id == current_user.id else fr.sender_id
        result.append(friend_id)

    return result