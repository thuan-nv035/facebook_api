from datetime import datetime
from typing import Optional

from pydantic import BaseModel

class ConversationCreate(BaseModel):
    member_ids: list[int]
    name: Optional[str] = None
    is_group: bool = False

class MessageCreate(BaseModel):
    receiver_id: int
    content: str
    reply_to_id: Optional[int] = None


class ReplyMessageResponse(BaseModel):
    id: int
    sender_id: int
    content: Optional[str] = None
    file_url: Optional[str] = None
    file_type: Optional[str] = None
    is_recalled: int

    class Config:
        from_attributes = True

class MessageResponse(BaseModel):
    id: int
    conversation_id: int
    sender_id: int
    content: Optional[str] = None
    file_url: Optional[str] = None
    file_type: Optional[str] = None
    is_recalled: int
    reply_to_id: Optional[int] = None
    reply_to: Optional[ReplyMessageResponse] = None
    created_at: datetime

    class Config:
        from_attributes = True

class MessageReactionCreate(BaseModel):
    reaction_type: str


class MessageReactionResponse(BaseModel):
    id: int
    message_id: int
    user_id: int
    reaction_type: str
    created_at: datetime

    class Config:
        from_attributes = True

class MessageEdit(BaseModel):
    content: str

class ConversationUpdate(BaseModel):
    name: Optional[str] = None
    image: Optional[str] = None


class AddMembersRequest(BaseModel):
    user_ids: list[int]

class JoinByInviteRequest(BaseModel):
    invite_code: str