from models import Notification
from websocket_manager import manager


async def create_notification(
    db,
    user_id: int,
    actor_id: int,
    type: str,
    message: str,
    target_type: str = None,
    target_id: int = None
):
    if user_id == actor_id:
        return None

    notification = Notification(
        user_id=user_id,
        actor_id=actor_id,
        type=type,
        message=message,
        target_type=target_type,
        target_id=target_id
    )

    db.add(notification)
    db.commit()
    db.refresh(notification)

    payload = {
        "id": notification.id,
        "user_id": notification.user_id,
        "actor_id": notification.actor_id,
        "type": notification.type,
        "message": notification.message,
        "target_type": notification.target_type,
        "target_id": notification.target_id,
        "is_read": notification.is_read,
        "created_at": str(notification.created_at)
    }

    await manager.send_notification(user_id, payload)

    return notification