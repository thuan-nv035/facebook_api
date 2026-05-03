from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from database import get_db
from models import User, Conversation, ConversationMember, ArchivedConversation
from services.auth import get_current_user

router = APIRouter(prefix="/api/v1/archive", tags=["Archive"])

@router.post("/conversations/{conversation_id}")
def archive_conversation(
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

    existing = db.query(ArchivedConversation).filter(
        ArchivedConversation.user_id == current_user.id,
        ArchivedConversation.conversation_id == conversation_id
    ).first()

    if existing:
        return {"message": "Cuộc trò chuyện đã được lưu trữ"}

    db.add(ArchivedConversation(
        user_id=current_user.id,
        conversation_id=conversation_id
    ))
    db.commit()

    return {"message": "Đã lưu trữ cuộc trò chuyện"}

@router.delete("/conversations/{conversation_id}")
def unarchive_conversation(
    conversation_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    archive = db.query(ArchivedConversation).filter(
        ArchivedConversation.user_id == current_user.id,
        ArchivedConversation.conversation_id == conversation_id
    ).first()

    if not archive:
        return {"message": "Cuộc trò chuyện chưa được lưu trữ"}

    db.delete(archive)
    db.commit()

    return {"message": "Đã bỏ lưu trữ cuộc trò chuyện"}

@router.get("/conversations")
def get_archived_conversations(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    archives = db.query(ArchivedConversation).filter(
        ArchivedConversation.user_id == current_user.id
    ).all()

    conversation_ids = [a.conversation_id for a in archives]

    conversations = db.query(Conversation).filter(
        Conversation.id.in_(conversation_ids)
    ).all()

    return conversations