import os
import sys
import uuid
import json
import logging
import contextvars
import hashlib
from datetime import datetime, timedelta

from fastapi import FastAPI, HTTPException, Depends, Request
from fastapi.security import OAuth2PasswordRequestForm
from sqlalchemy.orm import Session
from jose import jwt

# ==================================================
# LOCAL IMPORTS SAFE PATH
# ==================================================
BASE_DIR = os.path.dirname(os.path.abspath(__file__))

if BASE_DIR not in sys.path:
    sys.path.insert(0, BASE_DIR)

import models
import schemas
from database import SessionLocal, engine

# ==================================================
# OPENTELEMETRY (CLEAN)
# ==================================================
from opentelemetry import trace
from opentelemetry.sdk.resources import Resource
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import BatchSpanProcessor
from opentelemetry.exporter.otlp.proto.grpc.trace_exporter import OTLPSpanExporter

from opentelemetry.instrumentation.fastapi import FastAPIInstrumentor
from opentelemetry.instrumentation.requests import RequestsInstrumentor
from opentelemetry.instrumentation.sqlalchemy import SQLAlchemyInstrumentor

# ==================================================
# APP INIT
# ==================================================
app = FastAPI(title="Patient Service")

FastAPIInstrumentor.instrument_app(app)
RequestsInstrumentor().instrument()

# ==================================================
# CONFIG
# ==================================================
SECRET_KEY = "supersecretpatientkey"
ALGORITHM = "HS256"
ACCESS_TOKEN_EXPIRE_MINUTES = 60

SERVICE_NAME = os.getenv(
    "SERVICE_NAME",
    "patient-service"
)

OTEL_ENDPOINT = os.getenv(
    "OTEL_EXPORTER_OTLP_ENDPOINT",
    "localhost:4317"
)

OTEL_ENABLED = os.getenv(
    "OTEL_EXPORTER_ENABLED",
    "true"
).lower() in ("1", "true", "yes")

# ==================================================
# CORRELATION ID
# ==================================================
correlation_id_var = contextvars.ContextVar(
    "correlation_id",
    default=None
)

# ==================================================
# LOGGING (JSON STRUCTURED)
# ==================================================
class JsonFormatter(logging.Formatter):
    def format(self, record):
        try:
            span = trace.get_current_span()
            trace_id = span.get_span_context().trace_id
            trace_id = format(trace_id, "032x") if trace_id else None

        except Exception:
            trace_id = None

        log = {
            "timestamp": self.formatTime(record),
            "level": record.levelname,
            "message": record.getMessage(),
            "correlation_id": correlation_id_var.get(),
            "trace_id": trace_id,
        }

        if record.exc_info:
            log["exception"] = self.formatException(
                record.exc_info
            )

        return json.dumps(log)


handler = logging.StreamHandler()
handler.setFormatter(JsonFormatter())

root_logger = logging.getLogger()
root_logger.setLevel(logging.INFO)

if not root_logger.handlers:
    root_logger.addHandler(handler)

# ==================================================
# OPEN TELEMETRY INIT
# ==================================================
resource = Resource.create({
    "service.name": "patient-service"
})

provider = TracerProvider(
    resource=resource
)

trace.set_tracer_provider(provider)

if OTEL_ENABLED:
    exporter = OTLPSpanExporter(
        endpoint="http://localhost:4317",
        insecure=True
    )

    provider.add_span_processor(
        BatchSpanProcessor(exporter)
    )

try:
    SQLAlchemyInstrumentor().instrument(
        engine=engine
    )

except Exception as e:
    logging.warning(
        f"SQLAlchemy instrumentation failed: {e}"
    )

# ==================================================
# MIDDLEWARE
# ==================================================
from starlette.middleware.base import BaseHTTPMiddleware


class CorrelationIdMiddleware(BaseHTTPMiddleware):

    async def dispatch(
        self,
        request: Request,
        call_next
    ):
        req_id = (
            request.headers.get("X-Request-ID")
            or str(uuid.uuid4())
        )

        correlation_id_var.set(req_id)

        response = await call_next(request)

        response.headers["X-Request-ID"] = req_id

        return response


app.add_middleware(
    CorrelationIdMiddleware
)

# ==================================================
# DATABASE
# ==================================================
def get_db():
    db = SessionLocal()

    try:
        yield db

    finally:
        db.close()

# ==================================================
# PASSWORD UTILITIES
# ==================================================
def get_password_hash(password: str):
    return hashlib.sha256(
        password.encode()
    ).hexdigest()


def verify_password(
    plain_password: str,
    hashed_password: str
):
    return (
        hashlib.sha256(
            plain_password.encode()
        ).hexdigest()
        == hashed_password
    )

# ==================================================
# JWT
# ==================================================
def create_access_token(data: dict):

    payload = data.copy()

    expire = datetime.utcnow() + timedelta(
        minutes=ACCESS_TOKEN_EXPIRE_MINUTES
    )

    payload.update({
        "exp": expire
    })

    return jwt.encode(
        payload,
        SECRET_KEY,
        algorithm=ALGORITHM
    )

# ==================================================
# STARTUP
# ==================================================
@app.on_event("startup")
def startup():

    logging.info(
        "Patient service starting up"
    )

    models.Base.metadata.create_all(
        bind=engine
    )

    logging.info(
        "Database initialized"
    )

# ==================================================
# ROUTES
# ==================================================
@app.get("/")
def root():
    return {
        "message": "Patient Service Running"
    }


@app.post(
    "/register",
    response_model=schemas.PatientOut
)
def register(
    patient: schemas.PatientCreate,
    db: Session = Depends(get_db)
):

    existing_patient = (
        db.query(models.Patient)
        .filter(
            models.Patient.email
            == patient.email
        )
        .first()
    )

    if existing_patient:
        raise HTTPException(
            status_code=400,
            detail="Email already registered"
        )

    new_patient = models.Patient(
        name=patient.name,
        email=patient.email,
        hashed_password=get_password_hash(
            patient.password
        ),
        created_at=datetime.utcnow()
    )

    db.add(new_patient)
    db.commit()
    db.refresh(new_patient)

    return new_patient


@app.post(
    "/login",
    response_model=schemas.Token
)
def login(
    form_data: OAuth2PasswordRequestForm = Depends(),
    db: Session = Depends(get_db)
):

    patient = (
        db.query(models.Patient)
        .filter(
            models.Patient.email
            == form_data.username
        )
        .first()
    )

    if (
        not patient
        or not verify_password(
            form_data.password,
            patient.hashed_password
        )
    ):
        raise HTTPException(
            status_code=401,
            detail="Invalid credentials"
        )

    access_token = create_access_token({
        "sub": str(patient.id),
        "email": patient.email
    })

    return {
        "access_token": access_token,
        "token_type": "bearer"
    }


@app.get(
    "/profile/{patient_id}",
    response_model=schemas.PatientOut
)
def get_profile(
    patient_id: int,
    db: Session = Depends(get_db)
):

    patient = (
        db.query(models.Patient)
        .filter(
            models.Patient.id == patient_id
        )
        .first()
    )

    if not patient:
        raise HTTPException(
            status_code=404,
            detail="Patient not found"
        )

    return patient
