# Healthcare Microservices Platform

A production-style Healthcare Management System built using FastAPI Microservices Architecture with Distributed Tracing, Structured Logging, OpenTelemetry, and Jaeger Observability.

---

# Architecture

```text
Client
   │
   ▼
┌─────────────────┐
│  Auth Service   │
└────────┬────────┘
         │
         ▼
┌─────────────────┐
│ Patient Service │
└────────┬────────┘
         │
         ▼
┌──────────────────────┐
│ Appointment Service  │
└────────┬─────────────┘
         │
         ▼
┌─────────────────┐
│ Report Service  │
└─────────────────┘

         │
         ▼

 OpenTelemetry
         │
         ▼

      Jaeger
```

---

# Services

## 1. Auth Service

### Responsibilities

* User Registration
* User Login
* JWT Authentication
* Role Based Access Control
* Profile Management

### APIs

| Method | Endpoint               |
| ------ | ---------------------- |
| POST   | /auth/register         |
| POST   | /auth/login            |
| GET    | /profile               |
| PUT    | /users/update          |
| PUT    | /users/change-password |
| GET    | /admin                 |

---

## 2. Patient Service

### Responsibilities

* Patient Registration
* Patient Login
* Patient Profile Management

### APIs

| Method | Endpoint              |
| ------ | --------------------- |
| POST   | /register             |
| POST   | /login                |
| GET    | /profile/{patient_id} |

---

## 3. Appointment Service

### Responsibilities

* Doctor Listing
* Appointment Booking
* Appointment Cancellation
* Appointment History
* Patient Validation through Patient Service

### APIs

| Method | Endpoint                  |
| ------ | ------------------------- |
| GET    | /doctors                  |
| POST   | /appointments             |
| DELETE | /appointments/{id}        |
| GET    | /appointments/{patientId} |

### Sample Payload

```json
{
  "patientId": "101",
  "doctorName": "Dr Sharma",
  "specialization": "Cardiology",
  "appointmentDate": "2026-06-01",
  "time": "11:30 AM"
}
```

---

## 4. Report Service

### Responsibilities

* Upload Medical Reports
* Store Reports in AWS S3
* Local File Storage Fallback
* Generate Download URLs
* View Patient Reports

### APIs

| Method | Endpoint             |
| ------ | -------------------- |
| POST   | /upload-report       |
| GET    | /reports/{patientId} |

---

# Observability

## OpenTelemetry

All services are instrumented using OpenTelemetry.

### Instrumented Components

* FastAPI Requests
* SQLAlchemy Queries
* Inter-Service HTTP Requests
* Custom Business Operations

---

## Jaeger Distributed Tracing

Integrated Jaeger for end-to-end request tracing.

### Traced Services

* auth-service
* patient-service
* appointment-service
* report-service

### Features

* Distributed Tracing
* Request Lifecycle Tracking
* Trace Propagation
* Database Span Collection
* HTTP Request Spans

---

## Structured Logging

JSON-based logging implemented across services.

### Log Fields

```json
{
  "timestamp": "",
  "level": "",
  "message": "",
  "trace_id": "",
  "correlation_id": ""
}
```

---

## Correlation IDs

Each incoming request generates or propagates:

```text
X-Request-ID
```

allowing traceability across microservices.

---

# Technology Stack

## Backend

* Python 3.13
* FastAPI
* SQLAlchemy
* Pydantic
* JWT Authentication

## Database

* PostgreSQL / MySQL
* SQLAlchemy ORM

## Cloud Storage

* AWS S3
* boto3

## Observability

* OpenTelemetry
* Jaeger
* Structured Logging

## DevOps

* Docker
* Docker Compose

---

# Environment Variables

## Common

```env
OTEL_EXPORTER_ENABLED=true
OTEL_EXPORTER_OTLP_ENDPOINT=http://localhost:4317
SERVICE_NAME=<service-name>
```

## AWS

```env
S3_BUCKET_NAME=your_bucket
AWS_ACCESS_KEY_ID=your_key
AWS_SECRET_ACCESS_KEY=your_secret
AWS_DEFAULT_REGION=us-east-1
```

---

# Running Jaeger

```bash
docker run -d \
--name jaeger \
-p 16686:16686 \
-p 4317:4317 \
-p 4318:4318 \
jaegertracing/all-in-one:latest
```

Jaeger UI:

```text
http://localhost:16686
```

---

# Running Services

## Auth Service

```bash
uvicorn main:app --reload --port 8000
```

## Patient Service

```bash
uvicorn main:app --reload --port 8001
```

## Report Service

```bash
uvicorn main:app --reload --port 8002
```

## Appointment Service

```bash
uvicorn main:app --reload --port 8003
```

---

# Implemented Features

✅ JWT Authentication

✅ Role-Based Authorization

✅ Patient Management

✅ Appointment Booking

✅ Medical Report Upload

✅ AWS S3 Integration

✅ SQLAlchemy ORM

✅ OpenTelemetry Instrumentation

✅ Distributed Tracing with Jaeger

✅ Structured JSON Logging

✅ Correlation ID Tracking

✅ Inter-Service Communication

✅ Dockerized Observability Stack

---

# Future Enhancements

* Prometheus Metrics
* Grafana Dashboards
* Kubernetes Deployment
* CI/CD Pipeline using GitHub Actions
* ELK Stack Integration
* API Gateway
* Service Discovery
* Distributed Caching with Redis
