from sqlalchemy.orm import Session
from model import User, Message
from passlib.hash import bcrypt
from schemas import UserCreate, MessageCreate, MessageOut

def create_user(db: Session, user: UserCreate):
    hashed_pw = bcrypt.hash(user.password)
    db_user = User(username=user.username, hashed_password=hashed_pw)
    db.add(db_user)
    db.commit()
    db.refresh(db_user)
    return db_user


def create_message(db: Session, sender_id: int, message: MessageCreate):
    db_msg = Message(sender_id=sender_id, receiver_id=message.receiver_id, content=message.content)
    db.add(db_msg)
    db.commit()
    db.refresh(db_msg)
    return db_msg

def get_messages_between_users(db: Session, user1_id: int, user2_id: int):
    messages = db.query(Message).filter(
        ((Message.sender_id == user1_id) & (Message.receiver_id == user2_id)) |
        ((Message.sender_id == user2_id) & (Message.receiver_id == user1_id))
    ).order_by(Message.timestamp).all()

    return [MessageOut.from_orm_with_nickname(m) for m in messages]



def get_all_users(db: Session, skip: int = 0, limit: int = 100):
    return db.query(User).offset(skip).limit(limit).all()