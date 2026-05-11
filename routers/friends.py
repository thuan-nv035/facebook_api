from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from sqlalchemy import or_, and_

from database import get_db
from models import User, FriendRequest
from services.auth import get_current_user, is_blocked
from services.notification import create_notification
from fastapi.param_functions import Query

router = APIRouter(prefix="/api/v1/friends", tags=["Friends"])

def get_friend_request_between(db: Session, user_a_id: int, user_b_id: int):
    return db.query(FriendRequest).filter(
        or_(
            and_(
                FriendRequest.sender_id == user_a_id,
                FriendRequest.receiver_id == user_b_id
            ),
            and_(
                FriendRequest.sender_id == user_b_id,
                FriendRequest.receiver_id == user_a_id
            )
        )
    ).first()

def get_friendship_status(db: Session, current_user_id: int, other_user_id: int):
    if current_user_id == other_user_id:
        return {
            "status": "self",
            "request_id": None
        }

    request = get_friend_request_between(
        db=db,
        user_a_id=current_user_id,
        user_b_id=other_user_id
    )

    if not request:
        return {
            "status": "not_friend",
            "request_id": None
        }

    if request.status == "accepted":
        return {
            "status": "friends",
            "request_id": request.id
        }

    if request.status == "pending":
        if request.sender_id == current_user_id:
            return {
                "status": "request_sent",
                "request_id": request.id
            }

        return {
            "status": "request_received",
            "request_id": request.id
        }

    if request.status == "rejected":
        return {
            "status": "rejected",
            "request_id": request.id
        }

    if request.status == "cancelled":
        return {
            "status": "not_friend",
            "request_id": request.id
        }

    return {
        "status": "not_friend",
        "request_id": None
    }


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
    q: str = Query("", description="Tìm kiếm theo tên"),
    limit: int = Query(30, ge=1, le=100),    
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    query = db.query(User).filter(User.id != current_user.id)
    
    if q.strip():
        keyword = f"%{q.strip()}%"
        query = query.filter(
            or_(
                User.full_name.ilike(keyword),
                User.email.ilike(keyword)
            )
        )
    
    users = query.order_by(User.id.desc()).limit(limit).all()

    result = []

    for user in users:
        friendship = get_friendship_status(
            db=db,
            current_user_id=current_user.id,
            other_user_id=user.id
        )

        result.append({
            "id": user.id,
            "full_name": user.full_name,
            "email": user.email,
            "avatar": user.avatar,
            "bio": getattr(user, "bio", None),
            "friendship_status": friendship["status"],
            "friend_request_id": friendship["request_id"]
        })
    return result