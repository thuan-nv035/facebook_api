from datetime import datetime
from typing import Optional

from pydantic import BaseModel


class PostCreate(BaseModel):
    content: str
    image: Optional[str] = None


class PostResponse(BaseModel):
    id: int
    content: str
    image: Optional[str] = None
    user_id: int
    created_at: datetime

    class Config:
        from_attributes = True