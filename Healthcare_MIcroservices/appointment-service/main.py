import os
import sys
import uuid
import json
import logging
import contextvars
from datetime import datetime

import requests
from fastapi import FastAPI, HTTPException, Depends, Request
from sqlalchemy.orm import Session

# ==================================================
# LOCAL IMPORTS SAFE PATH
# ==================================================
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
if BASE_DIR not in sys.path:
    sys.path.insert(0, BASE_DIR)

import models, schemas
from database import SessionLocal, engine

# ==================================================
# OPENTELEMETRY (CLEAN)
# ==================================================
from opentelemetry import trace
from opentelemetry.sdk.resources import Resource
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import BatchSpanProcessor, ConsoleSpanExporter
from opentelemetry.exporter.otlp.proto.grpc.trace_exporter import OTLPSpanExporter
from opentelemetry.instrumentation.fastapi import FastAPIInstrumentor
from opentelemetry.instrumentation.requests import RequestsInstrumentor
from opentelemetry.instrumentation.sqlalchemy import SQLAlchemyInstrumentor

# ==================================================
# APP INIT
# ==================================================
app = FastAPI(title="Appointment Service")

FastAPIInstrumentor.instrument_app(app)
from opentelemetry.instrumentation.requests import RequestsInstrumentor


RequestsInstrumentor().instrument()

# ==================================================
# ENV CONFIG
# ==================================================
SERVICE_NAME = os.getenv("SERVICE_NAME", "appointment-service")

OTEL_ENDPOINT = os.getenv("OTEL_EXPORTER_OTLP_ENDPOINT", "localhost:4317")
OTEL_ENABLED = os.getenv("OTEL_EXPORTER_ENABLED", "true").lower() in ("1", "true", "yes")

PATIENT_SERVICE_URL = os.getenv("PATIENT_SERVICE_URL", "http://localhost:8001")

# ==================================================
# CORRELATION ID
# ==================================================
correlation_id_var = contextvars.ContextVar("correlation_id", default=None)

# ==================================================
# LOGGING (JSON STRUCTURED)
# ==================================================
class JsonFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
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
            log["exception"] = self.formatException(record.exc_info)

        return json.dumps(log)


handler = logging.StreamHandler()
handler.setFormatter(JsonFormatter())

root_logger = logging.getLogger()
root_logger.setLevel(logging.INFO)

if not root_logger.handlers:
    root_logger.addHandler(handler)

# ==================================================
# OPENTELEMETRY INIT (SINGLE CLEAN BLOCK)
# ==================================================
resource = Resource.create({
    "service.name": "appointment-service"
})

provider = TracerProvider(resource=resource)
trace.set_tracer_provider(provider)

if OTEL_ENABLED:
    exporter = OTLPSpanExporter(
    endpoint="http://localhost:4317",
    insecure=True)
    provider.add_span_processor(BatchSpanProcessor(exporter))
# else:
#     provider.add_span_processor(BatchSpanProcessor(ConsoleSpanExporter()))

# SQLAlchemy instrumentation
try:
    SQLAlchemyInstrumentor().instrument(engine=engine)
except Exception as e:
    logging.warning(f"SQLAlchemy instrumentation failed: {e}")

# ==================================================
# MIDDLEWARE
# ==================================================
from starlette.middleware.base import BaseHTTPMiddleware


class CorrelationIdMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        req_id = request.headers.get("X-Request-ID") or str(uuid.uuid4())
        correlation_id_var.set(req_id)

        response = await call_next(request)
        response.headers["X-Request-ID"] = req_id
        return response


app.add_middleware(CorrelationIdMiddleware)

# ==================================================
# SAMPLE DATA
# ==================================================
sample_doctors = [
    {"id": 1, "name": "Dr Sharma", "specialization": "Cardiology"},
    {"id": 2, "name": "Dr Reddy", "specialization": "Neurology"},
    {"id": 3, "name": "Dr Gupta", "specialization": "Orthopedics"},
]

# ==================================================
# STARTUP
# ==================================================
@app.on_event("startup")
def startup():
    logging.info("Appointment service starting up")
    models.Base.metadata.create_all(bind=engine)
    logging.info("Database initialized")

# ==================================================
# DB DEPENDENCY
# ==================================================
def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()

# ==================================================
# ROUTES
# ==================================================
@app.get("/")
def root():
    return {"message": "Appointment Service Running"}


@app.get("/doctors", response_model=list[schemas.DoctorOut])
def list_doctors():
    return sample_doctors


@app.post("/appointments", response_model=schemas.AppointmentOut)
def create_appointment(
    appointment: schemas.AppointmentCreate,
    db: Session = Depends(get_db)
):
    headers = {
        "X-Request-ID": correlation_id_var.get() or str(uuid.uuid4())
    }

    # Validate patient via patient-service
    try:
        resp = requests.get(
            f"{PATIENT_SERVICE_URL}/profile/{appointment.patientId}",
            headers=headers,
            timeout=5
        )

        if resp.status_code == 404:
            raise HTTPException(status_code=400, detail="Invalid patient ID")

        resp.raise_for_status()

    except requests.RequestException as e:
        logging.error(f"Patient service error: {e}")
        raise HTTPException(status_code=502, detail="Patient service unavailable")

    # Check slot availability
    existing = db.query(models.Appointment).filter(
        models.Appointment.doctor_name == appointment.doctorName,
        models.Appointment.appointment_date == appointment.appointmentDate,
        models.Appointment.time == appointment.time,
        models.Appointment.status == "booked",
    ).first()

    if existing:
        raise HTTPException(status_code=400, detail="Slot already booked")

    # Create appointment
    db_appointment = models.Appointment(
        patient_id=appointment.patientId,
        doctor_name=appointment.doctorName,
        specialization=appointment.specialization,
        appointment_date=appointment.appointmentDate,
        time=appointment.time,
        status="booked",
        created_at=datetime.utcnow(),
    )

    db.add(db_appointment)
    db.commit()
    db.refresh(db_appointment)

    return db_appointment


@app.get("/appointments/{patient_id}", response_model=list[schemas.AppointmentOut])
def get_appointments(patient_id: str, db: Session = Depends(get_db)):
    return db.query(models.Appointment).filter(
        models.Appointment.patient_id == patient_id
    ).all()


@app.delete("/appointments/{appointment_id}")
def cancel_appointment(appointment_id: int, db: Session = Depends(get_db)):
    appointment = db.query(models.Appointment).filter(
        models.Appointment.id == appointment_id
    ).first()

    if not appointment:
        raise HTTPException(status_code=404, detail="Appointment not found")

    appointment.status = "cancelled"
    db.commit()

    return {
        "message": "Appointment cancelled",
        "appointment_id": appointment_id
    }