import os
import shutil
from uuid import uuid4

from fastapi import APIRouter, Depends, HTTPException, UploadFile, File
from sqlalchemy.orm import Session

from database import get_db
from models import User, Conversation, ConversationMember
from services.auth import get_current_user
from websocket_manager import manager
from schemas.messages import ConversationUpdate, AddMembersRequest

router = APIRouter(prefix="/api/v1/conversations", tags=["Conversation Settings"])


def get_conversation_or_404(db: Session, conversation_id: int):
    conversation = db.query(Conversation).filter(
        Conversation.id == conversation_id
    ).first()

    if not conversation:
        raise HTTPException(404, "Cuộc trò chuyện không tồn tại")

    if conversation.status == "deleted":
        raise HTTPException(404, "Nhóm đã bị xóa")

    return conversation


def check_is_member(db: Session, conversation_id: int, user_id: int):
    member = db.query(ConversationMember).filter(
        ConversationMember.conversation_id == conversation_id,
        ConversationMember.user_id == user_id
    ).first()

    if not member:
        raise HTTPException(403, "Bạn không thuộc cuộc trò chuyện này")

    return member


def check_is_group(conversation: Conversation):
    if conversation.is_group != 1:
        raise HTTPException(400, "Chức năng này chỉ dùng cho nhóm")


def check_is_creator(conversation: Conversation, user_id: int):
    if conversation.creator_id != user_id:
        raise HTTPException(403, "Chỉ người tạo nhóm mới có quyền thực hiện thao tác này")

def get_member(db: Session, conversation_id: int, user_id: int):
    return db.query(ConversationMember).filter(
        ConversationMember.conversation_id == conversation_id,
        ConversationMember.user_id == user_id
    ).first()

def check_is_owner(db: Session, conversation_id: int, user_id: int):
    member = get_member(db, conversation_id, user_id)

    if not member or member.role != "owner":
        raise HTTPException(403, "Chỉ trưởng nhóm mới có quyền thực hiện thao tác này")

    return member


def check_is_admin_or_owner(db: Session, conversation_id: int, user_id: int):
    member = get_member(db, conversation_id, user_id)

    if not member or member.role not in ["owner", "admin"]:
        raise HTTPException(403, "Chỉ trưởng nhóm hoặc quản trị viên mới có quyền")

    return member

@router.patch("/{conversation_id}/settings")
async def update_group_settings(
    conversation_id: int,
    data: ConversationUpdate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    conversation = get_conversation_or_404(db, conversation_id)

    check_is_group(conversation)
    check_is_member(db, conversation_id, current_user.id)
    check_is_admin_or_owner(db, conversation_id, current_user.id)

    if data.name is not None:
        if not data.name.strip():
            raise HTTPException(400, "Tên nhóm không được để trống")
        conversation.name = data.name.strip()

    if data.image is not None:
        conversation.image = data.image

    db.commit()
    db.refresh(conversation)

    members = db.query(ConversationMember).filter(
        ConversationMember.conversation_id == conversation_id
    ).all()

    member_ids = [m.user_id for m in members]

    await manager.send_to_many(member_ids, {
        "type": "conversation_updated",
        "conversation_id": conversation.id,
        "name": conversation.name,
        "image": conversation.image,
        "updated_by": current_user.id
    })

    return {
        "message": "Đã cập nhật nhóm",
        "conversation": {
            "id": conversation.id,
            "name": conversation.name,
            "image": conversation.image,
            "is_group": conversation.is_group,
            "creator_id": conversation.creator_id
        }
    }

@router.post("/{conversation_id}/upload-image")
async def upload_group_image(
    conversation_id: int,
    file: UploadFile = File(...),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    conversation = get_conversation_or_404(db, conversation_id)

    check_is_group(conversation)
    check_is_member(db, conversation_id, current_user.id)
    check_is_admin_or_owner(db, conversation_id, current_user.id)

    allowed_types = ["image/jpeg", "image/png", "image/webp"]

    if file.content_type not in allowed_types:
        raise HTTPException(400, "Chỉ cho phép ảnh JPG, PNG, WEBP")

    os.makedirs("uploads/groups", exist_ok=True)

    ext = file.filename.split(".")[-1]
    filename = f"{uuid4()}.{ext}"
    file_path = f"uploads/groups/{filename}"

    with open(file_path, "wb") as buffer:
        shutil.copyfileobj(file.file, buffer)

    conversation.image = f"/uploads/groups/{filename}"

    db.commit()
    db.refresh(conversation)

    members = db.query(ConversationMember).filter(
        ConversationMember.conversation_id == conversation_id
    ).all()

    member_ids = [m.user_id for m in members]

    await manager.send_to_many(member_ids, {
        "type": "conversation_image_updated",
        "conversation_id": conversation.id,
        "image": conversation.image,
        "updated_by": current_user.id
    })

    return {
        "message": "Đã cập nhật ảnh nhóm",
        "image": conversation.image
    }

@router.post("/{conversation_id}/members")
async def add_members(
    conversation_id: int,
    data: AddMembersRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    conversation = get_conversation_or_404(db, conversation_id)

    check_is_group(conversation)
    check_is_member(db, conversation_id, current_user.id)
    check_is_admin_or_owner(db, conversation_id, current_user.id)

    added_users = []

    for user_id in data.user_ids:
        user = db.query(User).filter(User.id == user_id).first()

        if not user:
            continue

        existing = db.query(ConversationMember).filter(
            ConversationMember.conversation_id == conversation_id,
            ConversationMember.user_id == user_id
        ).first()

        if existing:
            continue

        db.add(ConversationMember(
            conversation_id=conversation_id,
            user_id=user_id
        ))

        added_users.append(user_id)

    db.commit()

    members = db.query(ConversationMember).filter(
        ConversationMember.conversation_id == conversation_id
    ).all()

    member_ids = [m.user_id for m in members]

    await manager.send_to_many(member_ids, {
        "type": "conversation_members_added",
        "conversation_id": conversation_id,
        "added_users": added_users,
        "added_by": current_user.id
    })

    return {
        "message": "Đã thêm thành viên",
        "added_users": added_users
    }

@router.delete("/{conversation_id}/members/{user_id}")
async def remove_member(
    conversation_id: int,
    user_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    conversation = get_conversation_or_404(db, conversation_id)

    check_is_group(conversation)
    check_is_member(db, conversation_id, current_user.id)
    current_member = check_is_admin_or_owner(db, conversation_id, current_user.id)

    if user_id == conversation.creator_id:
        raise HTTPException(400, "Không thể xóa người tạo nhóm")

    member = db.query(ConversationMember).filter(
        ConversationMember.conversation_id == conversation_id,
        ConversationMember.user_id == user_id
    ).first()

    if member.role == "owner":
        raise HTTPException(400, "Không thể xóa trưởng nhóm")

    if current_member.role == "admin" and member.role == "admin":
        raise HTTPException(403, "Admin không thể xóa admin khác")

    if current_member.role == "admin" and member.role == "owner":
        raise HTTPException(403, "Admin không thể xóa trưởng nhóm")

    if not member:
        raise HTTPException(404, "User không có trong nhóm")

    db.delete(member)
    db.commit()

    members = db.query(ConversationMember).filter(
        ConversationMember.conversation_id == conversation_id
    ).all()

    member_ids = [m.user_id for m in members]
    member_ids.append(user_id)

    await manager.send_to_many(member_ids, {
        "type": "conversation_member_removed",
        "conversation_id": conversation_id,
        "removed_user_id": user_id,
        "removed_by": current_user.id
    })

    return {
        "message": "Đã xóa thành viên khỏi nhóm",
        "removed_user_id": user_id
    }

@router.delete("/{conversation_id}/leave")
async def leave_group(
    conversation_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    conversation = get_conversation_or_404(db, conversation_id)

    check_is_group(conversation)

    member = check_is_member(db, conversation_id, current_user.id)

    if conversation.creator_id == current_user.id:
        raise HTTPException(
            400,
            "Người tạo nhóm không thể rời nhóm. Hãy xóa nhóm hoặc chuyển quyền trước."
        )

    db.delete(member)
    db.commit()

    members = db.query(ConversationMember).filter(
        ConversationMember.conversation_id == conversation_id
    ).all()

    member_ids = [m.user_id for m in members]
    member_ids.append(current_user.id)

    await manager.send_to_many(member_ids, {
        "type": "conversation_member_left",
        "conversation_id": conversation_id,
        "user_id": current_user.id
    })

    return {
        "message": "Đã rời nhóm"
    }

@router.delete("/{conversation_id}")
async def delete_group(
    conversation_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    conversation = get_conversation_or_404(db, conversation_id)

    check_is_group(conversation)
    check_is_creator(conversation, current_user.id)

    conversation.status = "deleted"
    db.commit()

    members = db.query(ConversationMember).filter(
        ConversationMember.conversation_id == conversation_id
    ).all()

    member_ids = [m.user_id for m in members]

    await manager.send_to_many(member_ids, {
        "type": "conversation_deleted",
        "conversation_id": conversation_id,
        "deleted_by": current_user.id
    })

    return {
        "message": "Đã xóa nhóm"
    }

@router.get("/{conversation_id}/settings")
def get_group_settings(
    conversation_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    conversation = get_conversation_or_404(db, conversation_id)

    check_is_member(db, conversation_id, current_user.id)

    members = db.query(ConversationMember).filter(
        ConversationMember.conversation_id == conversation_id
    ).all()

    member_ids = [m.user_id for m in members]

    users = db.query(User).filter(
        User.id.in_(member_ids)
    ).all()

    return {
        "id": conversation.id,
        "name": conversation.name,
        "image": conversation.image,
        "is_group": conversation.is_group,
        "creator_id": conversation.creator_id,
        "status": conversation.status,
        "members": [
            {
                "id": u.id,
                "full_name": u.full_name,
                "avatar": u.avatar,
                "role": get_member(db, conversation_id, u.id).role
            }
            for u in users
        ]
    }

@router.patch("/{conversation_id}/transfer-owner/{new_owner_id}")
async def transfer_group_owner(
    conversation_id: int,
    new_owner_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    conversation = get_conversation_or_404(db, conversation_id)

    check_is_group(conversation)
    check_is_member(db, conversation_id, current_user.id)
    check_is_creator(conversation, current_user.id)

    if new_owner_id == current_user.id:
        raise HTTPException(400, "Bạn đang là trưởng nhóm rồi")

    new_owner_member = db.query(ConversationMember).filter(
        ConversationMember.conversation_id == conversation_id,
        ConversationMember.user_id == new_owner_id
    ).first()

    if not new_owner_member:
        raise HTTPException(404, "Người nhận quyền không thuộc nhóm này")

    user = db.query(User).filter(User.id == new_owner_id).first()

    if not user:
        raise HTTPException(404, "User không tồn tại")

    conversation.creator_id = new_owner_id

    old_owner = get_member(db, conversation_id, current_user.id)
    new_owner = get_member(db, conversation_id, new_owner_id)

    old_owner.role = "admin"
    new_owner.role = "owner"

    db.commit()
    db.refresh(conversation)

    members = db.query(ConversationMember).filter(
        ConversationMember.conversation_id == conversation_id
    ).all()

    member_ids = [m.user_id for m in members]

    await manager.send_to_many(member_ids, {
        "type": "conversation_owner_transferred",
        "conversation_id": conversation_id,
        "old_owner_id": current_user.id,
        "new_owner_id": new_owner_id
    })

    return {
        "message": "Đã chuyển quyền trưởng nhóm",
        "conversation_id": conversation_id,
        "old_owner_id": current_user.id,
        "new_owner_id": new_owner_id
    }

@router.patch("/{conversation_id}/members/{user_id}/promote-admin")
async def promote_admin(
    conversation_id: int,
    user_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    conversation = get_conversation_or_404(db, conversation_id)

    check_is_group(conversation)
    check_is_owner(db, conversation_id, current_user.id)

    member = get_member(db, conversation_id, user_id)

    if not member:
        raise HTTPException(404, "User không thuộc nhóm này")

    if member.role == "owner":
        raise HTTPException(400, "Trưởng nhóm đã có quyền cao nhất")

    member.role = "admin"
    db.commit()

    members = db.query(ConversationMember).filter(
        ConversationMember.conversation_id == conversation_id
    ).all()

    member_ids = [m.user_id for m in members]

    await manager.send_to_many(member_ids, {
        "type": "group_admin_promoted",
        "conversation_id": conversation_id,
        "user_id": user_id,
        "promoted_by": current_user.id
    })

    return {
        "message": "Đã bổ nhiệm quản trị viên",
        "user_id": user_id
    }

@router.patch("/{conversation_id}/members/{user_id}/demote-admin")
async def demote_admin(
    conversation_id: int,
    user_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    conversation = get_conversation_or_404(db, conversation_id)

    check_is_group(conversation)
    check_is_owner(db, conversation_id, current_user.id)

    member = get_member(db, conversation_id, user_id)

    if not member:
        raise HTTPException(404, "User không thuộc nhóm này")

    if member.role == "owner":
        raise HTTPException(400, "Không thể gỡ quyền trưởng nhóm")

    if member.role != "admin":
        raise HTTPException(400, "User này không phải admin")

    member.role = "member"
    db.commit()

    members = db.query(ConversationMember).filter(
        ConversationMember.conversation_id == conversation_id
    ).all()

    member_ids = [m.user_id for m in members]

    await manager.send_to_many(member_ids, {
        "type": "group_admin_demoted",
        "conversation_id": conversation_id,
        "user_id": user_id,
        "demoted_by": current_user.id
    })

    return {
        "message": "Đã gỡ quyền quản trị viên",
        "user_id": user_id
    }