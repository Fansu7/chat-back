from pydantic import BaseModel
from datetime import datetime

from model import Message

class UserCreate(BaseModel):
    username: str
    password: str

class UserOut(BaseModel):
    id: int
    username: str

    class Config:
        from_attributes = True

class MessageCreate(BaseModel):
    sender_nickname: str
    receiver_id: int
    content: str

class MessageOut(BaseModel):
    id: int
    sender_id: int
    receiver_id: int
    content: str
    timestamp: datetime
    sender_nickname: str

    @classmethod
    def from_orm_with_nickname(cls, message: Message):
        return cls(
            id=message.id,
            sender_id=message.sender_id,
            receiver_id=message.receiver_id,
            content=message.content,
            timestamp=message.timestamp,
            sender_nickname=message.sender.username
        )

    class Config:
        orm_mode = True
