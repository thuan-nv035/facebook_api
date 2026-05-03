from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session
from sqlalchemy import or_

from database import get_db
from models import User, Post, SearchHistory
from services.auth import get_current_user

router = APIRouter(prefix="/api/v1/search", tags=["Search"])

@router.get("/")
def search_all(
    q: str = Query(..., min_length=1),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    keyword = f"%{q}%"

    # lưu history
    db.add(SearchHistory(
        user_id=current_user.id,
        keyword=q
    ))
    db.commit()

    users = db.query(User).filter(
        or_(
            User.full_name.ilike(keyword),
            User.email.ilike(keyword)
        )
    ).limit(5).all()

    posts = db.query(Post).filter(
        Post.content.ilike(keyword)
    ).limit(5).all()

    return {
        "users": users,
        "posts": posts
    }

@router.get("/users")
def search_users(
    q: str,
    db: Session = Depends(get_db)
):
    keyword = f"%{q}%"

    return db.query(User).filter(
        User.full_name.ilike(keyword)
    ).all()

@router.get("/posts")
def search_posts(
    q: str,
    db: Session = Depends(get_db)
):
    keyword = f"%{q}%"

    return db.query(Post).filter(
        Post.content.ilike(keyword)
    ).all()

@router.get("/hashtags")
def search_hashtag(
    tag: str,
    db: Session = Depends(get_db)
):
    keyword = f"%#{tag}%"

    return db.query(Post).filter(
        Post.content.ilike(keyword)
    ).all()

@router.get("/history")
def get_history(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    return db.query(SearchHistory).filter(
        SearchHistory.user_id == current_user.id
    ).order_by(SearchHistory.created_at.desc()).limit(10).all()

@router.get("/suggest")
def suggest(
    q: str,
    db: Session = Depends(get_db)
):
    keyword = f"{q}%"

    users = db.query(User.full_name).filter(
        User.full_name.ilike(keyword)
    ).limit(5).all()

    return [u[0] for u in users]