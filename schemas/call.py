from pydantic import BaseModel


class CallResponse(BaseModel):
    id: int
    caller_id: int
    receiver_id: int
    call_type: str
    status: str
    duration: int

    class Config:
        from_attributes = True