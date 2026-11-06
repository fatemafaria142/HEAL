from sqlalchemy import Column, Integer, String, Date, Float, Boolean, ForeignKey, DateTime, CheckConstraint, Index, text, func
from sqlalchemy.orm import declarative_base, relationship

Base = declarative_base()

class Patient(Base):
    __tablename__ = 'patients'
    
    patient_id = Column(Integer, primary_key=True)
    name = Column(String(100), nullable=False)
    date_of_birth = Column(Date, nullable=False)
    gender = Column(String(10))
    city = Column(String(100))
    is_deceased = Column(Boolean, default=False)
    created_at = Column(DateTime, server_default=func.now())
    
    diagnoses = relationship("Diagnosis", back_populates="patient")
    visits = relationship("Visit", back_populates="patient")
    prescriptions = relationship("Prescription", back_populates="patient")
    lab_results = relationship("LabResult", back_populates="patient")
    social_history = relationship("SocialHistory", back_populates="patient", uselist=False)
    procedures = relationship("Procedure", back_populates="patient")
    imaging_results = relationship("ImagingResult", back_populates="patient")

    __table_args__ = (
        Index('idx_patient_city', 'city'),
    )

class DiagnosisCode(Base):
    __tablename__ = 'diagnosis_codes'
    
    code = Column(String(20), primary_key=True)
    name = Column(String(200), nullable=False)
    category = Column(String(100))

class Diagnosis(Base):
    __tablename__ = 'diagnoses'
    
    diagnosis_id = Column(Integer, primary_key=True)
    patient_id = Column(Integer, ForeignKey('patients.patient_id'), nullable=False)
    visit_id = Column(Integer, ForeignKey('visits.visit_id'), nullable=False)
    icd10_code = Column(String(20), ForeignKey('diagnosis_codes.code'))
    diagnosis_name = Column(String(200), nullable=False)
    diagnosis_date = Column(Date, nullable=False)
    status = Column(String(50))
    created_at = Column(DateTime, server_default=func.now())
    
    patient = relationship("Patient", back_populates="diagnoses")
    visit = relationship("Visit", back_populates="diagnoses")
    code_ref = relationship("DiagnosisCode")

    __table_args__ = (
        Index('idx_diag_patient', 'patient_id'),
        Index('idx_diag_visit', 'visit_id'),
    )

class Visit(Base):
    __tablename__ = 'visits'
    
    visit_id = Column(Integer, primary_key=True)
    patient_id = Column(Integer, ForeignKey('patients.patient_id'), nullable=False)
    visit_date = Column(Date, nullable=False)
    visit_type = Column(String(50))
    hospital = Column(String(100))
    department = Column(String(100))
    reason_for_visit = Column(String(500))
    discharge_status = Column(String(100))
    created_at = Column(DateTime, server_default=func.now())
    
    patient = relationship("Patient", back_populates="visits")
    vitals = relationship("Vitals", back_populates="visit")
    notes = relationship("ClinicalNote", back_populates="visit")
    diagnoses = relationship("Diagnosis", back_populates="visit")
    procedures = relationship("Procedure", back_populates="visit")

    __table_args__ = (
        Index('idx_visit_patient', 'patient_id'),
        Index('idx_visit_date', 'visit_date'),
    )

class Vitals(Base):
    __tablename__ = 'vitals'
    
    vital_id = Column(Integer, primary_key=True)
    patient_id = Column(Integer, ForeignKey('patients.patient_id'), nullable=False)
    visit_id = Column(Integer, ForeignKey('visits.visit_id'), nullable=False)
    height = Column(Float)
    weight = Column(Float)
    bmi = Column(Float)
    heart_rate = Column(Integer)
    bp_systolic = Column(Integer)
    bp_diastolic = Column(Integer)
    temperature = Column(Float)
    recorded_date = Column(Date, nullable=False)
    
    visit = relationship("Visit", back_populates="vitals")
    patient = relationship("Patient")

    __table_args__ = (
        CheckConstraint('bp_systolic > 0 AND bp_diastolic > 0', name='check_bp'),
        CheckConstraint('bmi > 5 AND bmi < 100', name='check_bmi'),
        Index('idx_vitals_visit', 'visit_id'),
    )

class ClinicalNote(Base):
    __tablename__ = 'clinical_notes'
    
    note_id = Column(Integer, primary_key=True)
    patient_id = Column(Integer, ForeignKey('patients.patient_id'), nullable=False)
    visit_id = Column(Integer, ForeignKey('visits.visit_id'), nullable=False)
    note_text = Column(String(2000), nullable=False)
    note_type = Column(String(50))
    note_date = Column(Date, nullable=False)
    
    visit = relationship("Visit", back_populates="notes")
    patient = relationship("Patient")

class Prescription(Base):
    __tablename__ = 'prescriptions'
    
    prescription_id = Column(Integer, primary_key=True)
    patient_id = Column(Integer, ForeignKey('patients.patient_id'), nullable=False)
    visit_id = Column(Integer, ForeignKey('visits.visit_id'), nullable=False)
    medication = Column(String(200), nullable=False)
    dosage = Column(String(100))
    start_date = Column(Date, nullable=False)
    end_date = Column(Date)
    prescribing_doctor = Column(String(100))
    indication = Column(String(500))
    
    patient = relationship("Patient", back_populates="prescriptions")
    visit = relationship("Visit")

    __table_args__ = (
        Index('idx_presc_patient', 'patient_id'),
    )

class LabResult(Base):
    __tablename__ = 'lab_results'
    
    lab_id = Column(Integer, primary_key=True)
    patient_id = Column(Integer, ForeignKey('patients.patient_id'), nullable=False)
    visit_id = Column(Integer, ForeignKey('visits.visit_id'), nullable=False)
    test_name = Column(String(200), nullable=False)
    test_date = Column(Date, nullable=False)
    result_value = Column(Float)
    unit = Column(String(50))
    reference_range = Column(String(100))
    flag = Column(String(20))
    
    patient = relationship("Patient", back_populates="lab_results")
    visit = relationship("Visit")

    __table_args__ = (
        CheckConstraint('result_value >= 0', name='check_lab_val'),
        Index('idx_lab_patient_test', 'patient_id', 'test_name'),
    )

class SocialHistory(Base):
    __tablename__ = 'social_history'
    
    social_id = Column(Integer, primary_key=True)
    patient_id = Column(Integer, ForeignKey('patients.patient_id'), nullable=False, unique=True)
    tobacco_use = Column(String(50))
    alcohol_use = Column(String(50))
    exercise_frequency = Column(String(50))
    dietary_preferences = Column(String(200))
    
    patient = relationship("Patient", back_populates="social_history")

class Procedure(Base):
    __tablename__ = 'procedures'
    
    procedure_id = Column(Integer, primary_key=True)
    patient_id = Column(Integer, ForeignKey('patients.patient_id'), nullable=False)
    visit_id = Column(Integer, ForeignKey('visits.visit_id'), nullable=False)
    procedure_date = Column(Date, nullable=False)
    procedure_name = Column(String(200), nullable=False)
    procedure_code = Column(String(50))
    performing_clinician = Column(String(100))
    
    patient = relationship("Patient", back_populates="procedures")
    visit = relationship("Visit", back_populates="procedures")

class ImagingResult(Base):
    __tablename__ = 'imaging_results'
    
    imaging_id = Column(Integer, primary_key=True)
    patient_id = Column(Integer, ForeignKey('patients.patient_id'), nullable=False)
    visit_id = Column(Integer, ForeignKey('visits.visit_id'), nullable=False)
    imaging_type = Column(String(100))
    body_site = Column(String(100))
    findings = Column(String(1000))
    imaging_date = Column(Date, nullable=False)
    
    patient = relationship("Patient", back_populates="imaging_results")
    visit = relationship("Visit")

