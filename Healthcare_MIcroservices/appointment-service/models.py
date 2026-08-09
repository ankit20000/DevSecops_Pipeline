from sqlalchemy import Column, Integer, String, DateTime
from database import Base


class Appointment(Base):

    __tablename__ = "appointments"

    id = Column(Integer, primary_key=True)
    patient_id = Column(String)
    doctor_name = Column(String)
    specialization = Column(String)
    appointment_date = Column(String)
    time = Column(String)
