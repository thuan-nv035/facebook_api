from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from database import get_db
from models import Follow, User
from services.auth import get_current_user, is_blocked

router = APIRouter(prefix="/follows", tags=["Follows"])


@router.post("/{user_id}")
def follow_user(
    user_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    if is_blocked(db, current_user.id, user_id):
        raise HTTPException(403, "Không thể follow")

    if user_id == current_user.id:
        raise HTTPException(status_code=400, detail="Không thể follow chính mình")

    user = db.query(User).filter(User.id == user_id).first()

    if not user:
        raise HTTPException(status_code=404, detail="User không tồn tại")

    existing = db.query(Follow).filter(
        Follow.follower_id == current_user.id,
        Follow.following_id == user_id
    ).first()

    if existing:
        db.delete(existing)
        db.commit()
        return {"message": "Đã bỏ follow"}

    follow = Follow(
        follower_id=current_user.id,
        following_id=user_id
    )

    db.add(follow)
    db.commit()

    return {"message": "Đã follow user"}