from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from database import get_db
from models import Comment, Post, User
from schemas.comments import CommentCreate, CommentResponse
from services.auth import get_current_user
from services.notification import create_notification
router = APIRouter(prefix="/api/v1/comments", tags=["Comments"])


@router.post("/{post_id}", response_model=CommentResponse)
async def create_comment(
    post_id: int,
    data: CommentCreate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    post = db.query(Post).filter(Post.id == post_id).first()

    if not post:
        raise HTTPException(status_code=404, detail="Bài viết không tồn tại")

    comment = Comment(
        content=data.content,
        post_id=post_id,
        user_id=current_user.id
    )

    db.add(comment)
    db.commit()
    db.refresh(comment)

    await create_notification(
        db=db,
        user_id=post.user_id,
        actor_id=current_user.id,
        type="comment",
        message=f"{current_user.full_name} đã bình luận bài viết của bạn",
        target_type="post",
        target_id=post.id
    )

    return comment