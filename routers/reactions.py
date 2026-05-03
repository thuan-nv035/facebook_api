from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from sqlalchemy import func

from database import get_db
from models import User, Post, Reaction
from services.auth import get_current_user
from schemas.reactions import ReactionCreate
from services.notification import create_notification

router = APIRouter(prefix="/api/v1/reactions", tags=["Reactions"])

ALLOWED_REACTIONS = ["like", "love", "haha", "wow", "sad", "angry"]


@router.post("/posts/{post_id}")
async def react_post(
    post_id: int,
    data: ReactionCreate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    if data.type not in ALLOWED_REACTIONS:
        raise HTTPException(400, "Reaction không hợp lệ")

    post = db.query(Post).filter(Post.id == post_id).first()

    if not post:
        raise HTTPException(404, "Bài viết không tồn tại")

    reaction = db.query(Reaction).filter(
        Reaction.user_id == current_user.id,
        Reaction.post_id == post_id
    ).first()

    if reaction:
        reaction.type = data.type
        db.commit()
        db.refresh(reaction)

        return {
            "message": "Đã đổi reaction",
            "reaction": reaction.type
        }

    reaction = Reaction(
        user_id=current_user.id,
        post_id=post_id,
        type=data.type
    )

    db.add(reaction)
    db.commit()
    db.refresh(reaction)

    await create_notification(
        db=db,
        user_id=post.user_id,
        actor_id=current_user.id,
        type="reaction",
        message=f"{current_user.full_name} đã bày tỏ cảm xúc về bài viết của bạn",
        target_type="post",
        target_id=post.id
    )

    return {
        "message": "Đã reaction bài viết",
        "reaction": reaction.type
    }


@router.delete("/posts/{post_id}")
def remove_reaction(
    post_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    reaction = db.query(Reaction).filter(
        Reaction.user_id == current_user.id,
        Reaction.post_id == post_id
    ).first()

    if not reaction:
        raise HTTPException(404, "Bạn chưa reaction bài này")

    db.delete(reaction)
    db.commit()

    return {"message": "Đã bỏ reaction"}


@router.get("/posts/{post_id}/summary")
def reaction_summary(
    post_id: int,
    db: Session = Depends(get_db)
):
    rows = db.query(
        Reaction.type,
        func.count(Reaction.id)
    ).filter(
        Reaction.post_id == post_id
    ).group_by(
        Reaction.type
    ).all()

    summary = {
        "like": 0,
        "love": 0,
        "haha": 0,
        "wow": 0,
        "sad": 0,
        "angry": 0
    }

    total = 0

    for reaction_type, count in rows:
        summary[reaction_type] = count
        total += count

    return {
        "post_id": post_id,
        "total": total,
        "summary": summary
    }