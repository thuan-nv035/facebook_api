from datetime import datetime

from sqlalchemy.orm import Session

from models import MutedConversation


def is_conversation_muted(db: Session, user_id: int, conversation_id: int):
    mute = db.query(MutedConversation).filter(
        MutedConversation.user_id == user_id,
        MutedConversation.conversation_id == conversation_id
    ).first()

    if not mute:
        return False

    if mute.muted_until is None:
        return True

    if mute.muted_until > datetime.utcnow():
        return True

    db.delete(mute)
    db.commit()
    return False