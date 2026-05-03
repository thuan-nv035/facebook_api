import shutil
from datetime import datetime
from uuid import uuid4

from fastapi import APIRouter, Depends, HTTPException, UploadFile, File
from sqlalchemy import func
from sqlalchemy.orm import Session
from database import get_db
from models import Post, User, Follow, FriendRequest, Like, Comment, HiddenPost, SavedPost, ReportPost, Reaction, \
    BlockUser
from schemas.post import PostCreate, PostResponse
from services.auth import get_current_user

router = APIRouter(prefix="/api/v1/posts", tags=["Posts"])


@router.post("/", response_model=PostResponse)
def create_post(
    data: PostCreate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    post = Post(
        content=data.content,
        image=data.image,
        user_id=current_user.id
    )

    db.add(post)
    db.commit()
    db.refresh(post)

    return post


@router.get("/", response_model=list[PostResponse])
def get_all_posts(db: Session = Depends(get_db)):
    return db.query(Post).order_by(Post.created_at.desc()).all()


@router.get("/feed", response_model=list[PostResponse])
def get_newsfeed(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    following_ids = db.query(Follow.following_id).filter(
        Follow.follower_id == current_user.id
    ).all()

    ids = [item[0] for item in following_ids]
    ids.append(current_user.id)

    posts = db.query(Post).filter(
        Post.user_id.in_(ids)
    ).order_by(Post.created_at.desc()).all()

    return posts


@router.delete("/{post_id}")
def delete_post(
    post_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    post = db.query(Post).filter(Post.id == post_id).first()

    if not post:
        raise HTTPException(status_code=404, detail="Không tìm thấy bài viết")

    if post.user_id != current_user.id:
        raise HTTPException(status_code=403, detail="Không có quyền xóa")

    db.delete(post)
    db.commit()

    return {"message": "Đã xóa bài viết"}

@router.post("/upload-image")
def upload_post_image(
    file: UploadFile = File(...)
):
    ext = file.filename.split(".")[-1]
    filename = f"{uuid4()}.{ext}"

    file_path = f"uploads/posts/{filename}"

    with open(file_path, "wb") as buffer:
        shutil.copyfileobj(file.file, buffer)

    return {
        "image_url": f"/uploads/posts/{filename}"
    }

@router.get("/feed/ranked")
def get_ranked_newsfeed(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    # Lấy danh sách bạn bè
    friend_rows = db.query(FriendRequest).filter(
        (
            (FriendRequest.sender_id == current_user.id) |
            (FriendRequest.receiver_id == current_user.id)
        ),
        FriendRequest.status == "accepted"
    ).all()

    friend_ids = []

    for fr in friend_rows:
        if fr.sender_id == current_user.id:
            friend_ids.append(fr.receiver_id)
        else:
            friend_ids.append(fr.sender_id)

    # Lấy danh sách following
    following_rows = db.query(Follow.following_id).filter(
        Follow.follower_id == current_user.id
    ).all()

    following_ids = [row[0] for row in following_rows]

    allowed_user_ids = list(set(friend_ids + following_ids + [current_user.id]))

    hidden_posts = db.query(HiddenPost.post_id).filter(
        HiddenPost.user_id == current_user.id
    ).all()

    hidden_ids = [h[0] for h in hidden_posts]

    blocked_ids = db.query(BlockUser.blocked_id).filter(
        BlockUser.blocker_id == current_user.id
    ).all()

    blocked_ids = [b[0] for b in blocked_ids]

    posts = db.query(
        Post,
        func.count(func.distinct(Reaction.id)).label("reaction_count"),
        func.count(func.distinct(Comment.id)).label("comment_count")
    ).outerjoin(
        Reaction, Reaction.post_id == Post.id
    ).outerjoin(
        Comment, Comment.post_id == Post.id
    ).filter(
        Post.user_id.in_(allowed_user_ids),
        ~Post.user_id.in_(blocked_ids),
        ~Post.id.in_(hidden_ids)
    ).group_by(
        Post.id
    ).all()

    result = []

    for post, reaction_count, comment_count in posts:
        friend_score = 30 if post.user_id in friend_ids else 0
        following_score = 15 if post.user_id in following_ids else 0
        self_score = 5 if post.user_id == current_user.id else 0

        engagement_score = reaction_count  * 3 + comment_count * 5

        # Bài mới được cộng điểm theo id lớn hơn
        recency_score = post.id * 0.1

        score = friend_score + following_score + self_score + engagement_score + recency_score

        result.append({
            "id": post.id,
            "content": post.content,
            "image": post.image,
            "user_id": post.user_id,
            "created_at": post.created_at,
            "reaction_count": reaction_count,
            "comment_count": comment_count,
            "score": score
        })

    result = sorted(result, key=lambda x: x["score"], reverse=True)

    return result

@router.post("/{post_id}/hide")
def hide_post(
    post_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    existing = db.query(HiddenPost).filter(
        HiddenPost.user_id == current_user.id,
        HiddenPost.post_id == post_id
    ).first()

    if existing:
        return {"message": "Đã ẩn rồi"}

    db.add(HiddenPost(
        user_id=current_user.id,
        post_id=post_id
    ))
    db.commit()

    return {"message": "Đã ẩn bài viết"}

@router.post("/{post_id}/save")
def save_post(
    post_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    existing = db.query(SavedPost).filter(
        SavedPost.user_id == current_user.id,
        SavedPost.post_id == post_id
    ).first()

    if existing:
        return {"message": "Đã lưu rồi"}

    db.add(SavedPost(
        user_id=current_user.id,
        post_id=post_id
    ))
    db.commit()

    return {"message": "Đã lưu bài viết"}

@router.get("/saved")
def get_saved_posts(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    saved = db.query(SavedPost).filter(
        SavedPost.user_id == current_user.id
    ).all()

    post_ids = [s.post_id for s in saved]

    return db.query(Post).filter(Post.id.in_(post_ids)).all()

@router.post("/{post_id}/report")
def report_post(
    post_id: int,
    reason: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    db.add(ReportPost(
        user_id=current_user.id,
        post_id=post_id,
        reason=reason
    ))
    db.commit()

    return {"message": "Đã báo cáo bài viết"}

@router.get("/explore/trending")
def trending_posts(
    db: Session = Depends(get_db)
):
    posts = db.query(
        Post,
        func.count(func.distinct(Reaction.id)).label("reaction_count"),
        func.count(func.distinct(Comment.id)).label("comment_count")
    ).outerjoin(
        Reaction, Reaction.post_id == Post.id
    ).outerjoin(
        Comment, Comment.post_id == Post.id
    ).group_by(
        Post.id
    ).all()

    result = []

    for post, reaction_count, comment_count in posts:
        hours = (datetime.utcnow() - post.created_at).total_seconds() / 3600

        if hours == 0:
            hours = 1

        score = (reaction_count * 2 + comment_count * 3) / hours

        result.append({
            "id": post.id,
            "content": post.content,
            "image": post.image,
            "user_id": post.user_id,
            "reaction_count": reaction_count,
            "comment_count": comment_count,
            "score": score
        })

    result = sorted(result, key=lambda x: x["score"], reverse=True)

    return result[:20]

@router.get("/explore/hashtags")
def trending_hashtags(
    db: Session = Depends(get_db)
):
    posts = db.query(Post.content).all()

    hashtag_count = {}

    for (content,) in posts:
        if not content:
            continue

        words = content.split()

        for w in words:
            if w.startswith("#"):
                tag = w.lower()

                hashtag_count[tag] = hashtag_count.get(tag, 0) + 1

    sorted_tags = sorted(hashtag_count.items(), key=lambda x: x[1], reverse=True)

    return sorted_tags[:10]

@router.get("/explore/users")
def suggested_users(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    # user chưa follow
    following_ids = db.query(Follow.following_id).filter(
        Follow.follower_id == current_user.id
    ).all()

    following_ids = [f[0] for f in following_ids]

    users = db.query(User).filter(
        ~User.id.in_(following_ids),
        User.id != current_user.id
    ).all()

    result = []

    for user in users:
        follower_count = db.query(Follow).filter(
            Follow.following_id == user.id
        ).count()

        result.append({
            "id": user.id,
            "full_name": user.full_name,
            "followers": follower_count
        })

    result = sorted(result, key=lambda x: x["followers"], reverse=True)

    return result[:10]

@router.get("/explore")
def explore_all(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    return {
        "trending_posts": trending_posts(db),
        "hashtags": trending_hashtags(db),
        "users": suggested_users(db, current_user)
    }