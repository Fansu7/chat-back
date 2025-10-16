from fastapi import FastAPI, Depends, HTTPException, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from fastapi.security import OAuth2PasswordBearer, OAuth2PasswordRequestForm
from sqlalchemy.orm import Session
from database import SessionLocal, engine
from model import Base, User
from typing import Dict
from datetime import timedelta, datetime, timezone
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
    # --- Auth: JWT -> user_id ---
    try:
        payload = jwt.decode(token, auth.SECRET_KEY, algorithms=[auth.ALGORITHM])
        user_id = payload.get("userId")
        user_record = None

        with SessionLocal() as db_lookup:
            if user_id is None:
                username = payload.get("sub")
                if not username:
                    await websocket.close(code=1008)
                    return
                user_record = db_lookup.query(User).filter(User.username == username).first()
                if not user_record:
                    await websocket.close(code=1008)
                    return
                user_id = user_record.id
            else:
                user_record = db_lookup.query(User).filter(User.id == int(user_id)).first()

        user_id = int(user_id)
        sender_nickname = (getattr(user_record, "nickname", None) 
                   or getattr(user_record, "username", None) 
                   or f"User{user_id}")

    except JWTError:
        await websocket.close(code=1008)
        return

    # --- Conexión activa ---
    await websocket.accept()
    active_connections.setdefault(user_id, set()).add(websocket)

    db: Session = SessionLocal()
    try:
        while True:
            data = await websocket.receive_json()

            receiver_id = data.get("receiver_id")
            content = (data.get("content") or "").strip()
            if receiver_id is None or not content:
                continue

            try:
                receiver_id = int(receiver_id)
            except (TypeError, ValueError):
                continue

            # --- Persistir mensaje ---
            db_msg = crud.create_message(
                db,
                sender_id=user_id,
                message=schemas.MessageCreate(
                    receiver_id=receiver_id,
                    content=content
                )
            )

            created_at = getattr(db_msg, "created_at", None)
            if isinstance(created_at, datetime):
                created_iso = created_at.astimezone(timezone.utc).isoformat()
            else:
                created_iso = datetime.now(timezone.utc).isoformat()

            # --- Payload completo para front ---
            payload_out = {
                "id": getattr(db_msg, "id", None),
                "sender_id": user_id,
                "receiver_id": receiver_id,
                "content": content,
                "created_at": created_iso,
                "sender_nickname": sender_nickname,
            }

            # Enviar a receptor
            for ws in list(active_connections.get(receiver_id, [])):
                try:
                    await ws.send_json(payload_out)
                except Exception:
                    active_connections.get(receiver_id, set()).discard(ws)

            # Eco a TODAS las conexiones del emisor (p.ej. varias pestañas)
            for ws in list(active_connections.get(user_id, [])):
                try:
                    await ws.send_json(payload_out)
                except Exception:
                    active_connections.get(user_id, set()).discard(ws)

    except WebSocketDisconnect:
        pass
    finally:
        db.close()
        conns = active_connections.get(user_id)
        if conns:
            conns.discard(websocket)
            if not conns:
                active_connections.pop(user_id, None)