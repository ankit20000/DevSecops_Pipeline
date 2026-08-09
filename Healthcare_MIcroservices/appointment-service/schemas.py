from pydantic import BaseModel
from datetime import datetime


class DoctorOut(BaseModel):
    id: int
    name: str
    specialization: str


class AppointmentCreate(BaseModel):
    patientId: int | str
    doctorName: str
    specialization: str
    appointmentDate: str
    time: str


class AppointmentOut(AppointmentCreate):
    id: int
    status: str
    created_at: datetime

    class Config:
        orm_mode = True
