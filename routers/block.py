from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from database import get_db
from models import (
    User,
    Conversation,
    ConversationMember,
    BlockUser,
    DeletedConversation,
    ArchivedConversation,
)
from services.auth import get_current_user

router = APIRouter(prefix="/api/v1/block", tags=["Block"])


def find_private_conversation(db: Session, user_a_id: int, user_b_id: int):
    user_a_conversations = db.query(ConversationMember.conversation_id).filter(
        ConversationMember.user_id == user_a_id
    ).all()

    user_b_conversations = db.query(ConversationMember.conversation_id).filter(
        ConversationMember.user_id == user_b_id
    ).all()

    ids_a = [item[0] for item in user_a_conversations]
    ids_b = [item[0] for item in user_b_conversations]

    common_ids = list(set(ids_a) & set(ids_b))

    if not common_ids:
        return None

    conversation = db.query(Conversation).filter(
        Conversation.id.in_(common_ids),
        Conversation.is_group == 0,
        Conversation.status != "deleted"
    ).first()

    return conversation


@router.post("/{user_id}")
def block_user(
    user_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    if user_id == current_user.id:
        raise HTTPException(400, "Bạn không thể tự chặn chính mình")

    user = db.query(User).filter(User.id == user_id).first()

    if not user:
        raise HTTPException(404, "User không tồn tại")

    existing = db.query(BlockUser).filter(
        BlockUser.blocker_id == current_user.id,
        BlockUser.blocked_id == user_id
    ).first()

    if not existing:
        db.add(BlockUser(
            blocker_id=current_user.id,
            blocked_id=user_id
        ))

    conversation = find_private_conversation(
        db=db,
        user_a_id=current_user.id,
        user_b_id=user_id
    )

    db.commit()

    return {
        "message": "Đã chặn người dùng",
        "blocked_user_id": user_id,
        "conversation_id": conversation.id if conversation else None
    }


@router.delete("/{user_id}")
def unblock_user(
    user_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    block = db.query(BlockUser).filter(
        BlockUser.blocker_id == current_user.id,
        BlockUser.blocked_id == user_id
    ).first()

    if not block:
        return {
            "message": "Bạn chưa chặn user này"
        }

    conversation = find_private_conversation(
        db=db,
        user_a_id=current_user.id,
        user_b_id=user_id
    )

    db.delete(block)

    # Gỡ chặn thì khôi phục conversation về sidebar chính
    if conversation:
        deleted = db.query(DeletedConversation).filter(
            DeletedConversation.user_id == current_user.id,
            DeletedConversation.conversation_id == conversation.id
        ).first()

        if deleted:
            db.delete(deleted)

        archived = db.query(ArchivedConversation).filter(
            ArchivedConversation.user_id == current_user.id,
            ArchivedConversation.conversation_id == conversation.id
        ).first()

        if archived:
            db.delete(archived)

    db.commit()

    return {
        "message": "Đã gỡ chặn người dùng",
        "unblocked_user_id": user_id,
        "conversation_id": conversation.id if conversation else None
    }


@router.get("/users")
def get_blocked_users(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    blocks = db.query(BlockUser).filter(
        BlockUser.blocker_id == current_user.id
    ).order_by(BlockUser.created_at.desc()).all()

    result = []

    for block in blocks:
        user = db.query(User).filter(User.id == block.blocked_id).first()

        if not user:
            continue

        conversation = find_private_conversation(
            db=db,
            user_a_id=current_user.id,
            user_b_id=user.id
        )

        result.append({
            "blocked_id": block.id,
            "user_id": user.id,
            "full_name": user.full_name,
            "email": user.email,
            "avatar": user.avatar,
            "conversation_id": conversation.id if conversation else None,
            "created_at": block.created_at
        })

    return result