from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from database import get_db
from models import Like, Post, User
from services.auth import get_current_user
from services.notification import create_notification
router = APIRouter(prefix="/likes", tags=["Likes"])


@router.post("/{post_id}")
async def like_post(
    post_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    post = db.query(Post).filter(Post.id == post_id).first()

    if not post:
        raise HTTPException(status_code=404, detail="Bài viết không tồn tại")

    existing_like = db.query(Like).filter(
        Like.user_id == current_user.id,
        Like.post_id == post_id
    ).first()

    if existing_like:
        db.delete(existing_like)
        db.commit()
        return {"message": "Đã bỏ like"}

    like = Like(user_id=current_user.id, post_id=post_id)

    db.add(like)
    db.commit()

    await create_notification(
        db=db,
        user_id=post.user_id,
        actor_id=current_user.id,
        type="like",
        message=f"{current_user.full_name} đã thích bài viết của bạn",
        target_type="post",
        target_id=post.id
    )

    return {"message": "Đã like bài viết"}