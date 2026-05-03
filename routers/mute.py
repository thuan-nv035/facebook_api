from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from datetime import datetime, timedelta

from database import get_db
from models import User, ConversationMember, MutedConversation
from services.auth import get_current_user

router = APIRouter(prefix="/api/v1/mute", tags=["Mute"])

@router.post("/conversations/{conversation_id}")
def mute_conversation(
    conversation_id: int,
    minutes: int | None = None,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    member = db.query(ConversationMember).filter(
        ConversationMember.conversation_id == conversation_id,
        ConversationMember.user_id == current_user.id
    ).first()

    if not member:
        raise HTTPException(403, "Bạn không thuộc cuộc trò chuyện này")

    muted_until = None
    if minutes:
        muted_until = datetime.utcnow() + timedelta(minutes=minutes)

    mute = db.query(MutedConversation).filter(
        MutedConversation.user_id == current_user.id,
        MutedConversation.conversation_id == conversation_id
    ).first()

    if mute:
        mute.muted_until = muted_until
    else:
        mute = MutedConversation(
            user_id=current_user.id,
            conversation_id=conversation_id,
            muted_until=muted_until
        )
        db.add(mute)

    db.commit()

    return {
        "message": "Đã tắt thông báo cuộc trò chuyện",
        "conversation_id": conversation_id,
        "muted_until": muted_until
    }

@router.delete("/conversations/{conversation_id}")
def unmute_conversation(
    conversation_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    mute = db.query(MutedConversation).filter(
        MutedConversation.user_id == current_user.id,
        MutedConversation.conversation_id == conversation_id
    ).first()

    if not mute:
        return {"message": "Cuộc trò chuyện chưa bị mute"}

    db.delete(mute)
    db.commit()

    return {"message": "Đã bật lại thông báo"}

@router.get("/conversations")
def get_muted_conversations(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    return db.query(MutedConversation).filter(
        MutedConversation.user_id == current_user.id
    ).all()