from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from database import get_db
from models import User, ConversationMember, PinnedConversation
from services.auth import get_current_user

router = APIRouter(prefix="/api/v1/pin", tags=["Pin"])

@router.post("/conversations/{conversation_id}")
def pin_conversation(
    conversation_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    member = db.query(ConversationMember).filter(
        ConversationMember.conversation_id == conversation_id,
        ConversationMember.user_id == current_user.id
    ).first()

    if not member:
        raise HTTPException(403, "Bạn không thuộc cuộc trò chuyện này")

    existing = db.query(PinnedConversation).filter(
        PinnedConversation.user_id == current_user.id,
        PinnedConversation.conversation_id == conversation_id
    ).first()

    if existing:
        return {"message": "Đã ghim rồi"}

    db.add(PinnedConversation(
        user_id=current_user.id,
        conversation_id=conversation_id
    ))
    db.commit()

    return {"message": "Đã ghim cuộc trò chuyện"}

@router.delete("/conversations/{conversation_id}")
def unpin_conversation(
    conversation_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    pin = db.query(PinnedConversation).filter(
        PinnedConversation.user_id == current_user.id,
        PinnedConversation.conversation_id == conversation_id
    ).first()

    if not pin:
        return {"message": "Chưa ghim"}

    db.delete(pin)
    db.commit()

    return {"message": "Đã bỏ ghim"}

@router.get("/conversations")
def get_pinned_conversations(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    return db.query(PinnedConversation).filter(
        PinnedConversation.user_id == current_user.id
    ).all()