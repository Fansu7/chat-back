from fastapi import FastAPI, Depends, HTTPException, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from fastapi.security import OAuth2PasswordBearer, OAuth2PasswordRequestForm
from sqlalchemy.orm import Session
from database import SessionLocal, engine
from model import Base, User
from typing import Dict
from datetime import timedelta
import crud, schemas, auth
from auth import get_current_user
from jose import jwt, JWTError 
from typing import Set

app = FastAPI()
oauth2_scheme = OAuth2PasswordBearer(tokenUrl="token")
origin = ["http://localhost:4200", "https://fansu7.github.io/pychat_front", "https://fansu7.github.io"]

app.add_middleware(
    CORSMiddleware,
    allow_origins=origin,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

Base.metadata.create_all(bind=engine)

def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()

@app.post("/register", response_model=schemas.UserOut)
def register(user: schemas.UserCreate, db: Session = Depends(get_db)):
    db_user = auth.get_user_by_username(db, user.username)
    if db_user:
        raise HTTPException(status_code=400, detail="Username already registered")
    return crud.create_user(db, user)

@app.get("/users", response_model=list[schemas.UserOut])
def get_users(skip: int = 0, limit: int = 100, db: Session = Depends(get_db)):
    return crud.get_all_users(db, skip=skip, limit=limit)

@app.post("/messages/", response_model=schemas.MessageOut)
def send_message(message: schemas.MessageCreate, db: Session = Depends(get_db), current_user: int = Depends(get_current_user)):
    return crud.create_message(db, sender_id=current_user, message=message)

@app.get("/messages/{other_user_id}", response_model=list[schemas.MessageOut])
def get_conversation(other_user_id: int, db: Session = Depends(get_db), current_user: int = Depends(get_current_user)):
    return crud.get_messages_between_users(db, user1_id=current_user, user2_id=other_user_id)

@app.post("/token")
def login(form_data: OAuth2PasswordRequestForm = Depends(), db: Session = Depends(get_db)):
    user = auth.authenticate_user(db, form_data.username, form_data.password)
    if not user:
        raise HTTPException(status_code=400, detail="Incorrect username or password")
    access_token_expires = timedelta(minutes=auth.ACCESS_TOKEN_EXPIRE_MINUTES)
    return {
        "access_token": auth.create_access_token(data={"sub": user.username, "userId": user.id}, expires_delta=access_token_expires), "token_type": "bearer"}



active_connections: Dict[int, Set[WebSocket]] = {}

@app.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket, token: str):
    try:
        payload = jwt.decode(token, auth.SECRET_KEY, algorithms=[auth.ALGORITHM])
        user_id = payload.get("userId")
        if user_id is None:
            username = payload.get("sub")
            if not username:
                await websocket.close(code=1008)
                return
            db_lookup: Session = SessionLocal()
            try:
                user = db_lookup.query(User).filter(User.username == username).first()
                if not user:
                    await websocket.close(code=1008)
                    return
                user_id = user.id
            finally:
                db_lookup.close()
        user_id = int(user_id)
    except JWTError:
        await websocket.close(code=1008)
        return

    await websocket.accept()
    if user_id not in active_connections:
        active_connections[user_id] = set()
    active_connections[user_id].add(websocket)
    print(f"[WebSocket CONNECTED] User {user_id}")

    db: Session = SessionLocal()

    try:
        while True:
            try:
                data = await websocket.receive_json()
                receiver_id = int(data["receiver_id"])
                content = (data.get("content") or "").strip()
                if not content:
                    continue

                msg_in = schemas.MessageCreate(
                    receiver_id=receiver_id,
                    content=content,
                )
                db_msg = crud.create_message(db, sender_id=user_id, message=msg_in)
                try:
                    out = schemas.MessageOut.from_orm_with_nickname(db_msg)
                except Exception:
                    out = db_msg

                payload_out = out.model_dump() 

                if receiver_id in active_connections:
                    dead = []
                    for ws in list(active_connections[receiver_id]):
                        try:
                            await ws.send_json(payload_out)
                        except Exception:
                            dead.append(ws)
                    for ws in dead:
                        active_connections[receiver_id].discard(ws)

                dead_self = []
                for ws in list(active_connections.get(user_id, [])):
                    try:
                        await ws.send_json(payload_out)
                    except Exception:
                        dead_self.append(ws)
                for ws in dead_self:
                    active_connections[user_id].discard(ws)

                print(f"[WebSocket LOG] from {user_id} to {receiver_id} - msg {payload_out.get('id')}")

            except Exception as e:
                print(f"[WebSocket ERROR] {e}")
                break

    except WebSocketDisconnect:
        print(f"[WebSocket DISCONNECTED] User {user_id}")
    finally:
        db.close()
        conns = active_connections.get(user_id)
        if conns and websocket in conns:
            conns.discard(websocket)
            if not conns:
                active_connections.pop(user_id, None)
