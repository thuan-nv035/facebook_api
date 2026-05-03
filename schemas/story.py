from datetime import datetime
from typing import Optional

from pydantic import BaseModel


class StoryCreate(BaseModel):
    content: Optional[str] = None
    image: Optional[str] = None


class StoryResponse(BaseModel):
    id: int
    user_id: int
    content: Optional[str] = None
    image: Optional[str] = None
    created_at: datetime
    expired_at: datetime

    class Config:
        from_attributes = True