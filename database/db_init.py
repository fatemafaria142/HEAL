import os
import random
import sys
import itertools
from datetime import datetime, timedelta
from pathlib import Path

_ROOT = Path(__file__).resolve().parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from database.models import Base, Patient, Diagnosis, Visit, Prescription, LabResult, Vitals, ClinicalNote, DiagnosisCode, SocialHistory, Procedure, ImagingResult
import config

DB_URL = config.DATABASE_URL

# Fixed anchor instead of datetime.now(): every date in the generated dataset is
# computed as an offset from this constant, so re-running the seeder on any date
# produces byte-identical rows (datetime.now() would drift the data day to day).
ANCHOR_NOW = datetime(2025, 6, 1)


def create_synthetic_data(session):
    random.seed(42)

    diag_codes = [
        DiagnosisCode(code="I10", name="Hypertension", category="Cardiovascular"),
        DiagnosisCode(code="E11", name="Type 2 Diabetes Mellitus", category="Endocrine"),
        DiagnosisCode(code="J45", name="Asthma", category="Pulmonary"),
        DiagnosisCode(code="I25", name="Chronic Ischemic Heart Disease", category="Cardiovascular"),
        DiagnosisCode(code="K21", name="GERD", category="Gastrointestinal")
    ]
    session.add_all(diag_codes)
    session.flush()

    first_names = [
        "Ayesha", "Rafiq", "Nusrat", "Karim", "Farhana", "Mahmud", "Shirin", "Tanvir",
        "Lamia", "Imran", "Salma", "Rezaul", "Jahanara", "Kamal", "Rubina", "Hasan",
        "Nasreen", "Shahid", "Rumana", "Faisal", "Maliha", "Adnan", "Tahmina", "Omar",
        "Sabrina", "Zahid", "Rowshan", "Arif", "Nazneen", "Badrul",
    ]
    last_names = [
        "Rahman", "Begum", "Chowdhury", "Haque", "Islam", "Khan", "Ahmed", "Hossain",
        "Uddin", "Akter", "Talukder", "Siddiqui", "Azad", "Mahmud", "Alam", "Chakraborty",
    ]
    pairs = list(itertools.product(first_names, last_names))
    random.shuffle(pairs)
    names = [f"{f} {l}" for f, l in pairs[:100]]
    
    cities = ["Dhaka", "Chittagong", "Sylhet", "Rajshahi", "Khulna"]
    genders = ["M", "F"]
    medications = {
        "Hypertension": ("Amlodipine", "5mg daily"),
        "Type 2 Diabetes Mellitus": ("Metformin", "500mg BID"),
        "Asthma": ("Salbutamol", "Inhaler PRN")
    }
    
    hospitals = ["Dhaka Medical", "Apollo", "Square", "United", "Evercare"]
    departments = ["Cardiology", "Endocrinology", "Pulmonology", "Internal Med"]

    patients = []
    for i, name in enumerate(names):
        age_group = random.random()
        if age_group < 0.10:
            age_days = random.randint(2*365, 17*365)
        elif age_group < 0.30:
            age_days = random.randint(66*365, 85*365)
        else:
            age_days = random.randint(19*365, 64*365)
        
        dob = ANCHOR_NOW - timedelta(days=age_days)
        patient = Patient(
            name=name,
            date_of_birth=dob,
            gender=random.choice(genders),
            city=random.choice(cities),
        )
        patients.append(patient)
    session.add_all(patients)
    session.flush()

    for patient in patients:
        tobacco = random.choice(["Never", "Never", "Never", "Current", "Former"])
        alcohol = random.choice(["None", "None", "Moderate", "Heavy"]) if tobacco != "Never" else random.choice(["None", "Moderate"])
        
        sh = SocialHistory(
            patient_id=patient.patient_id,
            tobacco_use=tobacco,
            alcohol_use=alcohol,
            exercise_frequency=random.choice(["Regular", "Occasional", "None"]),
            dietary_preferences="Balanced"
        )
        session.add(sh)

    for idx, patient in enumerate(patients):
        num_visits = random.randint(2, 6)
        base_start_offset = random.randint(0, 800)
        base_date = ANCHOR_NOW - timedelta(days=base_start_offset)
        
        is_multimorbid = (idx < 15)
        changing_diagnosis = (idx >= 15 and idx < 25)
        high_prescription_v = (idx % 8 == 0)
        imaging_after_htn = (idx >= 30 and idx < 35)
        notes_with_abnormal_vitals = (idx >= 45 and idx < 50)
        post_visit_diagnosis = (idx >= 50 and idx < 55)
        frequent_visits = (idx >= 60 and idx < 65)
        long_prescriptions = (idx >= 70 and idx < 75)
        presc_after_last_diag = (idx >= 75 and idx < 80)
        
        if is_multimorbid:
            current_codes = [diag_codes[0], diag_codes[1]]
        elif imaging_after_htn:
            current_codes = [diag_codes[0]]
        elif idx % 5 == 0:
            current_codes = [diag_codes[2]]
        else:
            current_codes = [diag_codes[idx % 2]]

        for v_idx in range(num_visits):
            gap_range = (15, 25) if frequent_visits else (30, 90)
            v_date = base_date + timedelta(days=v_idx * random.randint(*gap_range))
            if v_date > ANCHOR_NOW: continue

            visit = Visit(
                patient_id=patient.patient_id,
                visit_date=v_date,
                visit_type=random.choice(["OPD", "OPD", "Emergency", "Inpatient"]),
                hospital=random.choice(hospitals),
                department=random.choice(departments),
                reason_for_visit=random.choice(["Routine Follow-up", "Annual Checkup", "Symptom Management"]),
                discharge_status="Discharged"
            )
            session.add(visit)
            session.flush()

            target_code = current_codes[0]
            if changing_diagnosis and v_idx >= num_visits // 2:
                target_code = diag_codes[3]
            
            bmi_mean = 31.0 if "Diabetes" in target_code.name else 26.5
            bmi = max(15.0, min(50.0, random.gauss(bmi_mean, 5.5)))
            
            sbp_mean = 148.0 if "Hypertension" in target_code.name else 122.0
            if notes_with_abnormal_vitals and v_idx == 0:
                sbp = random.randint(145, 175)
            else:
                sbp = int(max(90, min(200, random.gauss(sbp_mean, 15))))
            dbp = int(sbp * 0.65 + random.randint(-5, 5))
            
            hr = int(max(50, min(120, random.gauss(75, 10))))

            vital = Vitals(
                patient_id=patient.patient_id,
                visit_id=visit.visit_id,
                height=170.0 + random.randint(-15, 15),
                weight=bmi * (1.72 * 1.72),
                bmi=round(bmi, 1),
                heart_rate=hr,
                bp_systolic=sbp,
                bp_diastolic=dbp,
                temperature=round(random.uniform(35.5, 39.0), 1),
                recorded_date=v_date
            )
            session.add(vital)

            is_last_visit = (v_idx == num_visits - 1)
            should_skip_diag = (presc_after_last_diag and is_last_visit)
            
            if not should_skip_diag:
                for code in current_codes:
                    final_code = code
                    if changing_diagnosis and v_idx >= num_visits // 2:
                        final_code = diag_codes[3]
                    
                    diag_date = v_date + timedelta(days=random.randint(2, 5)) if (post_visit_diagnosis and is_last_visit) else v_date
                    
                    diag = Diagnosis(
                        patient_id=patient.patient_id,
                        visit_id=visit.visit_id,
                        icd10_code=final_code.code,
                        diagnosis_name=final_code.name,
                        diagnosis_date=diag_date,
                        status="Active"
                    )

                    session.add(diag)

            if not(idx % 10 == 0 and v_idx == 0):
                num_meds = random.randint(2, 3) if high_prescription_v else 1
                for m_idx in range(num_meds):
                    duration = random.randint(100, 180) if long_prescriptions else random.randint(7, 45)
                    
                    med_key = current_codes[0].name if m_idx == 0 else random.choice(list(medications.keys()))
                    if med_key in medications:
                        med, dose = medications[med_key]
                        presc = Prescription(
                            patient_id=patient.patient_id,
                            visit_id=visit.visit_id,
                            medication=f"{med} ({m_idx})" if m_idx > 0 else med,
                            dosage=dose,
                            start_date=v_date,
                            end_date=v_date + timedelta(days=duration),
                            prescribing_doctor="Dr. Multi-Care",
                            indication=med_key
                        )
                        session.add(presc)

            is_lab_visit = (v_idx % 2 == 0) or (idx % 4 == 0)
            if is_lab_visit:
                num_labs = 2 if (idx < 20) else 1
                for l_idx in range(num_labs):
                    test_name = "HbA1c" if l_idx == 0 else "LDL"
                    is_outlier = (idx < 5)
                    if is_outlier:
                        val = random.uniform(18.0, 25.0)
                    elif idx < 20:
                        val = random.uniform(7.5, 11.0) if (l_idx == 0) else random.uniform(4.0, 6.5)
                    else:
                        is_high = random.random() < 0.4
                        val = random.uniform(7.5, 11.0) if is_high else random.uniform(4.0, 6.5)
                    
                    lab = LabResult(
                        patient_id=patient.patient_id,
                        visit_id=visit.visit_id,
                        test_name=test_name,
                        test_date=v_date,
                        result_value=round(val, 1),
                        unit="%" if test_name == "HbA1c" else "mg/dL",
                        flag="High" if (val > 7.0) else "Normal"
                    )
                    session.add(lab)
            
            if idx % 10 == 0 and v_idx == 1:
                proc = Procedure(patient_id=patient.patient_id, visit_id=visit.visit_id, procedure_date=v_date, procedure_name="ECG", procedure_code="93000", performing_clinician="Dr. Surgeon")
                session.add(proc)
            
            if (idx % 12 == 0 and v_idx == 0) or (imaging_after_htn and v_idx == 1):
                img_type = random.choice(["CT scan", "MRI", "X-ray", "Ultrasound"])
                img = ImagingResult(
                    patient_id=patient.patient_id, 
                    visit_id=visit.visit_id, 
                    imaging_type=img_type, 
                    body_site="Abdomen" if img_type != "MRI" else "Brain", 
                    findings="Research Case J8: Evaluation post-hypertension diagnosis", 
                    imaging_date=v_date
                )
                session.add(img)

            if (notes_with_abnormal_vitals and v_idx == 0) or (idx % 5 == 0):
                note = ClinicalNote(
                    patient_id=patient.patient_id,
                    visit_id=visit.visit_id,
                    note_text=f"Research Case J10: Patient presents with elevated BP ({sbp}/{dbp})." if notes_with_abnormal_vitals else "Routine visit note.",
                    note_type="Clinical Observation",
                    note_date=v_date
                )
                session.add(note)

    now = ANCHOR_NOW
    for patient in patients[:30]:
        days_ago = random.randint(1, 29)
        rec_dt = (now - timedelta(days=days_ago)).date()
        recent_visit = Visit(
            patient_id=patient.patient_id,
            visit_date=rec_dt,
            visit_type=random.choice(["OPD", "Emergency"]),
            hospital=random.choice(hospitals),
            department=random.choice(departments),
            reason_for_visit="Hypertension follow-up / BP check",
            discharge_status="Discharged",
        )
        session.add(recent_visit)
        session.flush()
        sbp = random.randint(142, 168)
        dbp = random.randint(88, 102)
        vital = Vitals(
            patient_id=patient.patient_id,
            visit_id=recent_visit.visit_id,
            height=165.0 + random.randint(0, 20),
            weight=random.uniform(68.0, 92.0),
            bmi=round(random.uniform(24.0, 32.0), 1),
            heart_rate=random.randint(72, 98),
            bp_systolic=sbp,
            bp_diastolic=dbp,
            temperature=round(random.uniform(36.2, 37.4), 1),
            recorded_date=rec_dt,
        )
        session.add(vital)

    session.commit()
    print(f"Successfully deployed Research Seeder v6 (Complex Logic & Specific Research Cases).")



def init_db():
    engine = create_engine(DB_URL)
    Base.metadata.drop_all(engine)
    Base.metadata.create_all(engine)
    
    Session = sessionmaker(bind=engine)
    session = Session()
    
    try:
        create_synthetic_data(session)
    except Exception as e:
        print(f"Error seeding database: {e}")
        session.rollback()
    finally:
        session.close()

if __name__ == "__main__":
    init_db()
