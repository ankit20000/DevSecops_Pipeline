import os
import sys
import uuid
import json
import logging
import contextvars
from datetime import datetime

import boto3
from fastapi import FastAPI, UploadFile, File, Depends, Request
from sqlalchemy.orm import Session

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
app = FastAPI(title="Report Service")

FastAPIInstrumentor.instrument_app(app)
RequestsInstrumentor().instrument()

# ==================================================
# ENV CONFIG
# ==================================================
SERVICE_NAME = os.getenv(
    "SERVICE_NAME",
    "report-service"
)

S3_BUCKET = os.getenv("S3_BUCKET_NAME")

AWS_REGION = os.getenv(
    "AWS_DEFAULT_REGION",
    "us-east-1"
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

            trace_id = (
                span.get_span_context().trace_id
            )

            trace_id = (
                format(trace_id, "032x")
                if trace_id
                else None
            )

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
# OPENTELEMETRY INIT
# ==================================================
resource = Resource.create({
    "service.name": "report-service"
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


class CorrelationIdMiddleware(
    BaseHTTPMiddleware
):

    async def dispatch(
        self,
        request: Request,
        call_next
    ):

        req_id = (
            request.headers.get(
                "X-Request-ID"
            )
            or str(uuid.uuid4())
        )

        correlation_id_var.set(req_id)

        response = await call_next(
            request
        )

        response.headers[
            "X-Request-ID"
        ] = req_id

        return response


app.add_middleware(
    CorrelationIdMiddleware
)

# ==================================================
# STARTUP
# ==================================================
@app.on_event("startup")
def startup():

    logging.info(
        "Report service starting up"
    )

    models.Base.metadata.create_all(
        bind=engine
    )

    logging.info(
        "Database initialized"
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
# S3 CLIENT
# ==================================================
def get_s3_client():

    endpoint = os.getenv(
        "S3_ENDPOINT_URL"
    )

    if endpoint:

        return boto3.client(
            "s3",
            region_name=AWS_REGION,
            endpoint_url=endpoint
        )

    return boto3.client(
        "s3",
        region_name=AWS_REGION
    )

# ==================================================
# ROUTES
# ==================================================
@app.get("/")
def root():

    return {
        "message":
        "Report Service Running"
    }


@app.post(
    "/upload-report",
    response_model=schemas.ReportOut
)
async def upload_report(
    patientId: str,
    file: UploadFile = File(...),
    db: Session = Depends(get_db)
):

    file_ext = os.path.splitext(
        file.filename
    )[1]

    object_key = (
        f"reports/"
        f"{patientId}/"
        f"{uuid.uuid4().hex}"
        f"{file_ext}"
    )

    content = await file.read()

    s3_url = None

    # =====================================
    # S3 Upload
    # =====================================
    try:

        if S3_BUCKET:

            client = get_s3_client()

            metadata = {}

            cid = (
                correlation_id_var.get()
            )

            if cid:
                metadata[
                    "correlation_id"
                ] = cid

            client.put_object(
                Bucket=S3_BUCKET,
                Key=object_key,
                Body=content,
                ContentType=file.content_type,
                Metadata=metadata
            )

            s3_url = (
                client.generate_presigned_url(
                    "get_object",
                    Params={
                        "Bucket": S3_BUCKET,
                        "Key": object_key
                    },
                    ExpiresIn=3600
                )
            )

    except Exception as e:

        logging.warning(
            f"S3 failed, "
            f"using local storage: {e}"
        )

    # =====================================
    # Local Storage Fallback
    # =====================================
    if not s3_url:

        base_dir = os.path.join(
            os.getcwd(),
            "storage",
            str(patientId)
        )

        os.makedirs(
            base_dir,
            exist_ok=True
        )

        local_path = os.path.join(
            base_dir,
            f"{uuid.uuid4().hex}"
            f"{file_ext}"
        )

        with open(
            local_path,
            "wb"
        ) as f:
            f.write(content)

        s3_url = (
            f"file://{local_path}"
        )

        object_key = local_path

    # =====================================
    # Save To DB
    # =====================================
    report = models.Report(
        patient_id=patientId,
        filename=file.filename,
        s3_key=object_key,
        s3_url=s3_url,
        uploaded_at=datetime.utcnow()
    )

    db.add(report)
    db.commit()
    db.refresh(report)

    return report


@app.get(
    "/reports/{patient_id}",
    response_model=list[
        schemas.ReportOut
    ]
)
def get_reports(
    patient_id: str,
    db: Session = Depends(get_db)
):

    return (
        db.query(models.Report)
        .filter(
            models.Report.patient_id
            == patient_id
        )
        .all()
    )
