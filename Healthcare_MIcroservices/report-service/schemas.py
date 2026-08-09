from pydantic import BaseModel
from datetime import datetime


class ReportCreate(BaseModel):
    patientId: str


class ReportOut(BaseModel):
    id: int
    patient_id: str
    filename: str
    s3_url: str
    uploaded_at: datetime

    class Config:
        orm_mode = True
