from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from sqlalchemy import or_, and_

from database import get_db
from models import User, FriendRequest
from services.auth import get_current_user, is_blocked
from services.notification import create_notification
from fastapi.param_functions import Query

router = APIRouter(prefix="/api/v1/friends", tags=["Friends"])
async def send_friend_ws(user_id: int, payload: dict):
    try:
        from routers.chat import manager

        await manager.send_to_user(user_id, payload)
    except Exception as e:
        print("Friend WebSocket error:", e)
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
            and_(
                FriendRequest.sender_id == current_user.id,
                FriendRequest.receiver_id == user_id
            ),
            and_(
                FriendRequest.sender_id == user_id,
                FriendRequest.receiver_id == current_user.id
            )
        )
    ).first()

    if existing:
        if existing.status == "accepted":
            raise HTTPException(400, "Hai người đã là bạn bè")

        if existing.status == "pending":
            raise HTTPException(400, "Đã gửi lời mời hoặc đang chờ xử lý")

        # Cho gửi lại nếu trước đó bị từ chối hoặc đã hủy
        existing.sender_id = current_user.id
        existing.receiver_id = user_id
        existing.status = "pending"

        db.commit()
        db.refresh(existing)

        fr = existing
    else:
        fr = FriendRequest(
            sender_id=current_user.id,
            receiver_id=user_id,
            status="pending"
        )

        db.add(fr)
        db.commit()
        db.refresh(fr)

    await create_notification(
        db=db,
        user_id=user_id,
        actor_id=current_user.id,
        type="friend_request",
        message=f"{current_user.full_name} đã gửi lời mời kết bạn"
    )

    await send_friend_ws(user_id, {
        "type": "friend_request_received",
        "request_id": fr.id,
        "friendship_status": "request_received",
        "user": {
            "id": current_user.id,
            "full_name": current_user.full_name,
            "email": current_user.email,
            "avatar": current_user.avatar
        }
    })

    return {
        "message": "Đã gửi lời mời",
        "request_id": fr.id,
        "friendship_status": "request_sent"
    }

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

    if fr.status != "pending":
        raise HTTPException(400, "Lời mời này không còn ở trạng thái chờ")

    sender = db.query(User).filter(User.id == fr.sender_id).first()

    if not sender:
        raise HTTPException(404, "Người gửi lời mời không tồn tại")

    fr.status = "accepted"
    db.commit()
    db.refresh(fr)

    await create_notification(
        db=db,
        user_id=fr.sender_id,
        actor_id=current_user.id,
        type="friend_accept",
        message=f"{current_user.full_name} đã chấp nhận lời mời kết bạn"
    )

    # Báo realtime cho User A - người đã gửi lời mời
    await send_friend_ws(fr.sender_id, {
        "type": "friend_request_accepted",
        "request_id": fr.id,
        "friendship_status": "friends",
        "user": {
            "id": current_user.id,
            "full_name": current_user.full_name,
            "email": current_user.email,
            "avatar": current_user.avatar
        }
    })

    # Báo realtime cho User B - người vừa accept, để UI của B cũng đồng bộ nếu cần
    await send_friend_ws(current_user.id, {
        "type": "friend_status_changed",
        "request_id": fr.id,
        "friendship_status": "friends",
        "user": {
            "id": sender.id,
            "full_name": sender.full_name,
            "email": sender.email,
            "avatar": sender.avatar
        }
    })

    return {
        "message": "Đã chấp nhận",
        "request_id": fr.id,
        "friendship_status": "friends"
    }

@router.post("/reject/{request_id}")
async def reject_request(
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

    if fr.status != "pending":
        raise HTTPException(400, "Lời mời này không còn ở trạng thái chờ")

    fr.status = "rejected"
    db.commit()
    db.refresh(fr)

    await send_friend_ws(fr.sender_id, {
        "type": "friend_request_rejected",
        "request_id": fr.id,
        "friendship_status": "rejected",
        "user": {
            "id": current_user.id,
            "full_name": current_user.full_name,
            "email": current_user.email,
            "avatar": current_user.avatar
        }
    })

    return {
        "message": "Đã từ chối",
        "request_id": fr.id,
        "friendship_status": "rejected"
    }

@router.delete("/cancel/{request_id}")
async def cancel_request(
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

    receiver_id = fr.receiver_id

    db.delete(fr)
    db.commit()

    await send_friend_ws(receiver_id, {
        "type": "friend_request_cancelled",
        "request_id": request_id,
        "friendship_status": "not_friend",
        "user": {
            "id": current_user.id,
            "full_name": current_user.full_name,
            "email": current_user.email,
            "avatar": current_user.avatar
        }
    })

    return {
        "message": "Đã hủy lời mời",
        "request_id": request_id,
        "friendship_status": "not_friend"
    }

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