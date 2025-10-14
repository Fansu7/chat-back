from fastapi import FastAPI, Depends, HTTPException, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from fastapi.security import OAuth2PasswordBearer, OAuth2PasswordRequestForm
from sqlalchemy.orm import Session
from database import SessionLocal, engine
from model import Base, User
from typing import Dict
from datetime import datetime, timedelta
import crud, schemas, auth
from auth import get_current_user

app = FastAPI()
oauth2_scheme = OAuth2PasswordBearer(tokenUrl="token")
origin = ["http://localhost:4200"]

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



active_connections: Dict[int, WebSocket] = {}

@app.websocket("/ws/{user_id}")
async def websocket_endpoint(websocket: WebSocket, user_id: int):
    await websocket.accept()
    active_connections[user_id] = websocket
    print(f"[WebSocket CONNECTED] User {user_id}")

    db: Session = SessionLocal()

    try:
        while True:
            try:
                data = await websocket.receive_json()
                sender_nickname = db.query(User).filter(User.id == user_id).first().username
                receiver_id = data["receiver_id"]
                message = data["message"]

                response = schemas.MessageCreate(
                    sender_nickname= sender_nickname,
                    receiver_id= receiver_id,
                    content= message
                )

                
                    

                # Enviar al receptor si está conectado
                if receiver_id in active_connections:
                    await active_connections[receiver_id].send_json(response.model_dump())

                # Echo al emisor también
                await websocket.send_json(response.model_dump())

                print(f"[WebSocket LOG] {user_id}")
                # Guardar en la base de datos
                crud.create_message(db, sender_id=user_id, message=response)

            except Exception as e:
                print(f"[WebSocket ERROR] {e}")
                break

    except WebSocketDisconnect:
        print(f"[WebSocket DISCONNECTED] User {user_id}")
    finally:
        db.close()
        active_connections.pop(user_id, None)
