from datetime import datetime
from typing import Optional

from pydantic import BaseModel


class NotificationResponse(BaseModel):
    id: int
    user_id: int
    actor_id: int
    type: str
    message: str
    target_type: Optional[str] = None
    target_id: Optional[int] = None
    is_read: int
    created_at: datetime

    class Config:
        from_attributes = True