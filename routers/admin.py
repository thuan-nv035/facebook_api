from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session
from sqlalchemy import func

from database import get_db
from models import User, Post, ReportPost, Notification
from services.auth import get_current_user, require_admin

router = APIRouter(prefix="/api/v1/admin", tags=["Admin"])

@router.get("/dashboard")
def dashboard(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    require_admin(current_user)

    total_users = db.query(User).count()
    total_posts = db.query(Post).count()
    total_reports = db.query(ReportPost).count()

    return {
        "users": total_users,
        "posts": total_posts,
        "reports": total_reports
    }

@router.get("/users")
def get_users(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    require_admin(current_user)
    return db.query(User).all()

@router.patch("/users/{user_id}/ban")
def ban_user(
    user_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    require_admin(current_user)

    user = db.query(User).filter(User.id == user_id).first()
    user.is_active = 0

    db.commit()

    return {"message": "Đã khóa user"}

@router.delete("/posts/{post_id}")
def delete_post_admin(
    post_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    require_admin(current_user)

    post = db.query(Post).filter(Post.id == post_id).first()

    if post:
        db.delete(post)
        db.commit()

    return {"message": "Đã xóa bài"}

@router.get("/reports")
def get_reports(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    require_admin(current_user)

    return db.query(ReportPost).order_by(
        ReportPost.created_at.desc()
    ).all()

@router.post("/reports/{report_id}/resolve")
def resolve_report(
    report_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    require_admin(current_user)

    report = db.query(ReportPost).filter(
        ReportPost.id == report_id
    ).first()

    if not report:
        return {"message": "Không tìm thấy report"}

    post = db.query(Post).filter(Post.id == report.post_id).first()

    if post:
        db.delete(post)

    db.delete(report)
    db.commit()

    return {"message": "Đã xử lý report"}

@router.get("/stats")
def stats(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    require_admin(current_user)

    posts_per_day = db.query(
        func.date(Post.created_at),
        func.count(Post.id)
    ).group_by(func.date(Post.created_at)).all()

    return {
        "posts_per_day": posts_per_day
    }