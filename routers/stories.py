from fastapi import APIRouter, Depends, HTTPException, UploadFile, File
from sqlalchemy.orm import Session
from datetime import datetime, timedelta
from uuid import uuid4
import shutil
import os

from database import get_db
from models import User, Story, FriendRequest, Follow
from schemas.story import StoryCreate, StoryResponse
from services.auth import get_current_user

router = APIRouter(prefix="/api/v1/stories", tags=["Stories"])


@router.post("/", response_model=StoryResponse)
def create_story(
    data: StoryCreate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    story = Story(
        user_id=current_user.id,
        content=data.content,
        image=data.image,
        expired_at=datetime.utcnow() + timedelta(hours=24)
    )

    db.add(story)
    db.commit()
    db.refresh(story)

    return story


@router.post("/upload-image")
def upload_story_image(
    file: UploadFile = File(...),
    current_user: User = Depends(get_current_user)
):
    os.makedirs("uploads/stories", exist_ok=True)

    ext = file.filename.split(".")[-1]
    filename = f"{uuid4()}.{ext}"
    file_path = f"uploads/stories/{filename}"

    with open(file_path, "wb") as buffer:
        shutil.copyfileobj(file.file, buffer)

    return {
        "image_url": f"/uploads/stories/{filename}"
    }


@router.get("/", response_model=list[StoryResponse])
def get_story_feed(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    friend_rows = db.query(FriendRequest).filter(
        (
            (FriendRequest.sender_id == current_user.id) |
            (FriendRequest.receiver_id == current_user.id)
        ),
        FriendRequest.status == "accepted"
    ).all()

    friend_ids = [
        fr.receiver_id if fr.sender_id == current_user.id else fr.sender_id
        for fr in friend_rows
    ]

    following_rows = db.query(Follow.following_id).filter(
        Follow.follower_id == current_user.id
    ).all()

    following_ids = [row[0] for row in following_rows]

    allowed_user_ids = list(set(friend_ids + following_ids + [current_user.id]))

    stories = db.query(Story).filter(
        Story.user_id.in_(allowed_user_ids),
        Story.expired_at > datetime.utcnow()
    ).order_by(Story.created_at.desc()).all()

    return stories


@router.get("/me", response_model=list[StoryResponse])
def get_my_stories(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    return db.query(Story).filter(
        Story.user_id == current_user.id,
        Story.expired_at > datetime.utcnow()
    ).order_by(Story.created_at.desc()).all()


@router.delete("/{story_id}")
def delete_story(
    story_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    story = db.query(Story).filter(Story.id == story_id).first()

    if not story:
        raise HTTPException(404, "Story không tồn tại")

    if story.user_id != current_user.id:
        raise HTTPException(403, "Không có quyền xóa story này")

    db.delete(story)
    db.commit()

    return {"message": "Đã xóa story"}