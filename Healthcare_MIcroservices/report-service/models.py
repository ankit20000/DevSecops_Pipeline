from sqlalchemy import Column, Integer, String
from database import Base

class Report(Base):
    __tablename__ = "reports"

    id = Column(Integer, primary_key=True)
    report_name = Column(String)