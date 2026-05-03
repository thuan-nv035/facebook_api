from pydantic import BaseModel


class ReactionCreate(BaseModel):
    type: str