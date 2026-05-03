import shutil
from uuid import uuid4

from fastapi import APIRouter, Depends, HTTPException, UploadFile, File
from sqlalchemy import or_
from sqlalchemy.orm import Session
from database import get_db
from models import User
from schemas.user import UserCreate, UserLogin, UserResponse, UserUpdate
from services.auth import hash_password, verify_password, create_access_token, get_current_user
from fastapi.security import OAuth2PasswordRequestForm
router = APIRouter(prefix="/api/v1/users", tags=["Users"])


@router.post("/register", response_model=UserResponse)
def register(data: UserCreate, db: Session = Depends(get_db)):
    user = db.query(User).filter(User.email == data.email).first()

    if user:
        raise HTTPException(status_code=400, detail="Email đã tồn tại")

    new_user = User(
        full_name=data.full_name,
        email=data.email,
        password=hash_password(data.password)
    )

    db.add(new_user)
    db.commit()
    db.refresh(new_user)

    return new_user


@router.post("/login")
def login(
    data: OAuth2PasswordRequestForm = Depends(),
    db: Session = Depends(get_db)
):
    user = db.query(User).filter(User.email == data.username).first()

    if not user or not verify_password(data.password, user.password):
        raise HTTPException(status_code=400, detail="Sai email hoặc mật khẩu")

    token = create_access_token({"user_id": user.id})

    return {
        "access_token": token,
        "token_type": "bearer"
    }

@router.get("/search")
def search_users(
    q: str = "",
    limit: int = 20,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    query = db.query(User).filter(User.id != current_user.id)

    if q.strip():
        keyword = f"%{q}%"
        query = query.filter(
                or_(
                User.full_name.ilike(keyword),
                User.email.ilike(keyword)
            )
        )

    users = query.limit(limit).all()

    return [
        {
            "id": user.id,
            "full_name": user.full_name,
            "email": user.email,
            "avatar": user.avatar
        }
        for user in users
    ]
@router.get("/me", response_model=UserResponse)
def get_me(current_user: User = Depends(get_current_user)):
    return current_user

@router.get("/{user_id}", response_model=UserResponse)
def get_user_profile(
        user_id: int,
        db: Session = Depends(get_db)
):
    user = db.query(User).filter(User.id == user_id).first()

    if not user:
        raise HTTPException(status_code=404, detail="User not found")

    return user

@router.put("/me", response_model=UserResponse)
def update_me(
        data: UserUpdate,
        db: Session = Depends(get_db),
        current_user: User = Depends(get_current_user)
):
    if data.full_name is not None:
        current_user.full_name = data.full_name

    if data.avatar is not None:
        current_user.avatar = data.avatar

    if data.bio is not None:
        current_user.bio = data.bio

    db.commit()
    db.refresh(current_user)

    return current_user

@router.post("/upload-avatar")
def upload_avatar(
    file: UploadFile = File(...),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    # tạo tên file random
    ext = file.filename.split(".")[-1]
    filename = f"{uuid4()}.{ext}"

    file_path = f"uploads/avatars/{filename}"

    # lưu file
    with open(file_path, "wb") as buffer:
        shutil.copyfileobj(file.file, buffer)

    # lưu vào DB
    current_user.avatar = f"/uploads/avatars/{filename}"
    db.commit()

    return {
        "avatar_url": current_user.avatar
    }