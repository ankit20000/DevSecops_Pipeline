from datetime import datetime, timedelta
from typing import Generator

from fastapi import FastAPI, Depends, HTTPException
from fastapi.security import OAuth2PasswordBearer, OAuth2PasswordRequestForm
from jose import jwt
from passlib.context import CryptContext
from sqlalchemy.orm import Session
from pydantic import BaseModel, EmailStr

from database import SessionLocal, engine
from models import Base, User

import os

# ==================================================
# OPEN TELEMETRY (CLEAN SETUP)
# ==================================================
from opentelemetry import trace
from opentelemetry.sdk.resources import Resource
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import BatchSpanProcessor, ConsoleSpanExporter
from opentelemetry.exporter.otlp.proto.grpc.trace_exporter import OTLPSpanExporter
from opentelemetry.instrumentation.fastapi import FastAPIInstrumentor

# -----------------------------
# App
# -----------------------------
app = FastAPI(title="Auth Service")

FastAPIInstrumentor.instrument_app(app)
from opentelemetry.instrumentation.requests import RequestsInstrumentor

RequestsInstrumentor().instrument()

# ==================================================
# CONFIG
# ==================================================
SECRET_KEY = "mysecretkey123"
ALGORITHM = "HS256"
ACCESS_TOKEN_EXPIRE_MINUTES = 30

oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/auth/login")

pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")

# ==================================================
# DATABASE
# ==================================================
def get_db() -> Generator:
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()

# ==================================================
# OPEN TELEMETRY INIT (CLEAN)
# ==================================================
SERVICE_NAME = os.getenv("SERVICE_NAME", "auth-service")

resource = Resource.create({
    "service.name": "auth-service"
})

provider = TracerProvider(resource=resource)
trace.set_tracer_provider(provider)

OTEL_ENDPOINT = os.getenv("OTEL_EXPORTER_OTLP_ENDPOINT", "localhost:4317")
OTEL_ENABLED = os.getenv("OTEL_EXPORTER_ENABLED", "true").lower() in ("1", "true", "yes")

if OTEL_ENABLED:
    exporter = OTLPSpanExporter(
    endpoint="http://localhost:4317",
    insecure=True
)
    provider.add_span_processor(BatchSpanProcessor(exporter))
# else:
#     provider.add_span_processor(BatchSpanProcessor(ConsoleSpanExporter()))

# ==================================================
# PASSWORD UTIL
# ==================================================
def hash_password(password: str) -> str:
    return pwd_context.hash(password)


def verify_password(plain: str, hashed: str) -> bool:
    return pwd_context.verify(plain, hashed)

# ==================================================
# JWT
# ==================================================
def create_access_token(data: dict):
    payload = data.copy()
    expire = datetime.utcnow() + timedelta(minutes=ACCESS_TOKEN_EXPIRE_MINUTES)
    payload.update({"exp": expire})
    return jwt.encode(payload, SECRET_KEY, algorithm=ALGORITHM)

# ==================================================
# AUTH DEPENDENCY
# ==================================================
def get_current_user(
    token: str = Depends(oauth2_scheme),
    db: Session = Depends(get_db)
):
    try:
        payload = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
        email = payload.get("email")

        if not email:
            raise HTTPException(status_code=401, detail="Invalid token")

    except Exception:
        raise HTTPException(status_code=401, detail="Invalid token")

    user = db.query(User).filter(User.email == email).first()

    if not user:
        raise HTTPException(status_code=401, detail="User not found")

    return user


def require_admin(current_user: User = Depends(get_current_user)):
    if current_user.role != "admin":
        raise HTTPException(status_code=403, detail="Admin only")
    return current_user

# ==================================================
# SCHEMA
# ==================================================
class UserCreate(BaseModel):
    username: str
    email: EmailStr
    password: str

# ==================================================
# ROUTES
# ==================================================
@app.get("/")
def home():
    return {"message": "Auth Service Running"}


@app.post("/auth/register")
def register(user: UserCreate, db: Session = Depends(get_db)):
    existing = db.query(User).filter(User.email == user.email).first()

    if existing:
        raise HTTPException(status_code=400, detail="Email already registered")

    new_user = User(
        name=user.username,
        email=user.email,
        password=hash_password(user.password),
        role="user"
    )

    db.add(new_user)
    db.commit()
    db.refresh(new_user)

    return {"message": "User registered successfully"}


@app.post("/auth/login")
def login(
    form_data: OAuth2PasswordRequestForm = Depends(),
    db: Session = Depends(get_db)
):
    user = db.query(User).filter(User.name == form_data.username).first()

    if not user or not verify_password(form_data.password, user.password):
        raise HTTPException(status_code=401, detail="Invalid credentials")

    token = create_access_token({
        "sub": user.name,
        "email": user.email,
        "role": user.role
    })

    return {"access_token": token, "token_type": "bearer"}


@app.get("/profile")
def profile(current_user: User = Depends(get_current_user)):
    return {
        "id": current_user.id,
        "name": current_user.name,
        "email": current_user.email
    }


@app.put("/users/update")
def update_user(
    name: str,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    current_user.name = name
    db.commit()
    db.refresh(current_user)
    return current_user


@app.put("/users/change-password")
def change_password(
    old_password: str,
    new_password: str,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    if not verify_password(old_password, current_user.password):
        raise HTTPException(status_code=400, detail="Wrong password")

    current_user.password = hash_password(new_password)
    db.commit()

    return {"message": "Password updated"}


@app.get("/admin")
def admin_panel(current_user: User = Depends(require_admin)):
    return {"message": "Welcome Admin"}

# ==================================================
# STARTUP
# ==================================================
@app.on_event("startup")
def startup():
    Base.metadata.create_all(bind=engine)
    print("Database tables created")