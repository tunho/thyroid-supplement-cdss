from fastapi import FastAPI, HTTPException, Depends, status
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from pydantic import BaseModel
import sqlite3
from datetime import datetime, timedelta
import jwt
import hashlib
from pathlib import Path
from typing import Any, Dict, List, Optional
import json

BASE_DIR = Path(__file__).resolve().parent
DB_PATH = BASE_DIR / "patients.db"
RAG_APP_ROOT = BASE_DIR.parent.parent
VIRTUAL_PATIENT_PATH = RAG_APP_ROOT / "data" / "samples" / "virtual_patients.json"
SECRET_KEY = "your-secret-key-change-in-production"
ALGORITHM = "HS256"
ACCESS_TOKEN_EXPIRE_MINUTES = 60 * 24  # 24 hours

security = HTTPBearer()

class PatientLoginRequest(BaseModel):
    patient_id: str
    password: str

class PatientRegisterRequest(BaseModel):
    patient_id: str
    password: str
    name: str
    conditions: str = ""
    medications: str = ""
    age: Optional[int] = None
    sex: str = "female"
    health_literacy: str = "general"  # expert / general / beginner
    preference_type: str = "moderate"  # active / moderate / conservative
    current_supplements: str = ""

class PatientProfile(BaseModel):
    patient_id: str
    name: str
    conditions: str
    medications: str
    age: Optional[int] = None
    sex: str = "female"
    health_literacy: str = "general"
    preference_type: str = "moderate"
    current_supplements: str = ""
    created_at: str


class PatientUpdateProfileRequest(BaseModel):
    name: Optional[str] = None
    conditions: Optional[str] = None
    medications: Optional[str] = None
    age: Optional[int] = None
    sex: Optional[str] = None
    health_literacy: Optional[str] = None
    preference_type: Optional[str] = None
    current_supplements: Optional[str] = None

class DoctorRegisterRequest(BaseModel):
    doctor_id: str
    password: str
    name: str
    specialty: str = "general"
    years_experience: int = 0
    supplement_attitude: str = "neutral"
    risk_tolerance: str = "moderate"

class DoctorLoginRequest(BaseModel):
    doctor_id: str
    password: str

class DoctorProfile(BaseModel):
    doctor_id: str
    name: str
    specialty: str
    years_experience: int
    supplement_attitude: str
    risk_tolerance: str
    created_at: str


class DoctorUpdateProfileRequest(BaseModel):
    specialty: str
    years_experience: int
    supplement_attitude: str
    risk_tolerance: str

class TokenResponse(BaseModel):
    access_token: str
    token_type: str
    patient_id: Optional[str] = None
    doctor_id: Optional[str] = None
    name: str
    role: str = "patient"


class VirtualPatientAccount(BaseModel):
    patient_id: str
    name: str
    conditions: str
    medications: str
    default_password: str

def init_db():
    """Initialize the patients database."""
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS patients (
            patient_id TEXT PRIMARY KEY,
            password_hash TEXT NOT NULL,
            name TEXT NOT NULL,
            conditions TEXT DEFAULT '',
            medications TEXT DEFAULT '',
            age INTEGER,
            sex TEXT DEFAULT 'female',
            health_literacy TEXT DEFAULT 'general',
            preference_type TEXT DEFAULT 'moderate',
            current_supplements TEXT DEFAULT '',
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """)
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS doctors (
            doctor_id TEXT PRIMARY KEY,
            password_hash TEXT NOT NULL,
            name TEXT NOT NULL,
            specialty TEXT DEFAULT 'general',
            years_experience INTEGER DEFAULT 0,
            supplement_attitude TEXT DEFAULT 'neutral',
            risk_tolerance TEXT DEFAULT 'moderate',
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """)
    conn.commit()
    conn.close()
    _migrate_db()


def _migrate_db():
    """기존 DB에 새 컬럼 추가 (없으면 추가, 있으면 무시)."""
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    new_columns = [
        ("patients", "age", "INTEGER"),
        ("patients", "sex", "TEXT DEFAULT 'female'"),
        ("patients", "health_literacy", "TEXT DEFAULT 'general'"),
        ("patients", "preference_type", "TEXT DEFAULT 'moderate'"),
        ("patients", "current_supplements", "TEXT DEFAULT ''"),
    ]
    for table, col, col_type in new_columns:
        try:
            cursor.execute(f"ALTER TABLE {table} ADD COLUMN {col} {col_type}")
        except Exception:
            pass
    conn.commit()
    conn.close()


def _load_virtual_patients() -> List[Dict[str, Any]]:
    if not VIRTUAL_PATIENT_PATH.exists():
        return []
    with open(VIRTUAL_PATIENT_PATH, "r", encoding="utf-8") as f:
        payload = json.load(f)
    return payload if isinstance(payload, list) else []


def _sex_from_json(raw: str) -> str:
    """JSON 'M'/'F' → DB 'male'/'female'."""
    return "male" if str(raw).strip().upper() == "M" else "female"


def seed_virtual_patients(default_password: str = "demo1234") -> None:
    """
    Seed auth DB using sample virtual patients.
    Only inserts rows that do not yet exist. Full profiles are set by
    refresh_virtual_patient_profiles() which runs immediately after.
    """
    patients = _load_virtual_patients()
    if not patients:
        return
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    password_hash = hash_password(default_password)
    for patient in patients:
        patient_id = str(patient.get("id", "")).strip()
        if not patient_id:
            continue
        name = str(patient.get("name") or patient.get("persona") or patient_id).strip()
        conditions = ", ".join(patient.get("conditions", []) or [])
        medications = ", ".join(patient.get("medications", []) or [])
        supplements = ", ".join(patient.get("current_supplements", []) or [])
        age = patient.get("age")
        sex = _sex_from_json(patient.get("sex", "F"))
        cursor.execute(
            "SELECT patient_id FROM patients WHERE patient_id = ?",
            (patient_id,),
        )
        if cursor.fetchone():
            continue
        cursor.execute(
            "INSERT INTO patients "
            "(patient_id, password_hash, name, conditions, medications, age, sex, current_supplements, health_literacy, preference_type) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (patient_id, password_hash, name, conditions, medications, age, sex, supplements, "general", "moderate"),
        )
    conn.commit()
    conn.close()


def refresh_virtual_patient_profiles(default_password: str = "demo1234") -> None:
    """
    Upsert vp-* patient rows from virtual_patients.json.
    Ensures age, sex, conditions, medications, current_supplements are always
    in sync with the JSON source, even after previous partial seeds.
    """
    patients = _load_virtual_patients()
    if not patients:
        return
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    password_hash = hash_password(default_password)
    for patient in patients:
        patient_id = str(patient.get("id", "")).strip()
        if not patient_id:
            continue
        name = str(patient.get("name") or patient.get("persona") or patient_id).strip()
        conditions = ", ".join(patient.get("conditions", []) or [])
        medications = ", ".join(patient.get("medications", []) or [])
        supplements = ", ".join(patient.get("current_supplements", []) or [])
        age = patient.get("age")
        sex = _sex_from_json(patient.get("sex", "F"))
        cursor.execute("SELECT patient_id FROM patients WHERE patient_id = ?", (patient_id,))
        if cursor.fetchone():
            cursor.execute(
                "UPDATE patients SET name=?, conditions=?, medications=?, age=?, sex=?, current_supplements=? "
                "WHERE patient_id=?",
                (name, conditions, medications, age, sex, supplements, patient_id),
            )
        else:
            cursor.execute(
                "INSERT INTO patients "
                "(patient_id, password_hash, name, conditions, medications, age, sex, current_supplements, health_literacy, preference_type) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (patient_id, password_hash, name, conditions, medications, age, sex, supplements, "general", "moderate"),
            )
    conn.commit()
    conn.close()


def seed_demo_patient(default_password: str = "demo1234") -> None:
    """Seed auth DB with a default demo patient account (general test user without diagnosis)."""
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    password_hash = hash_password(default_password)
    cursor.execute("SELECT patient_id FROM patients WHERE patient_id = 'patient01'")
    if cursor.fetchone():
        cursor.execute(
            "UPDATE patients SET name=?, conditions=?, medications=?, age=?, sex=?, health_literacy=?, preference_type=? "
            "WHERE patient_id='patient01'",
            ("데모환자", "", "", None, "female", "general", "moderate"),
        )
    else:
        cursor.execute(
            "INSERT INTO patients "
            "(patient_id, password_hash, name, conditions, medications, age, sex, health_literacy, preference_type) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
            ("patient01", password_hash, "데모환자", "", "", None, "female", "general", "moderate"),
        )
    conn.commit()
    conn.close()


def seed_doctors(default_password: str = "demo1234") -> None:
    """Seed auth DB with the dr_lee operator account."""
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    password_hash = hash_password(default_password)
    cursor.execute("SELECT doctor_id FROM doctors WHERE doctor_id = 'dr_lee'")
    if not cursor.fetchone():
        cursor.execute(
            "INSERT INTO doctors (doctor_id, password_hash, name, specialty, years_experience, supplement_attitude, risk_tolerance) "
            "VALUES (?, ?, ?, ?, ?, ?, ?)",
            ("dr_lee", password_hash, "이갑상", "내분비내과", 10, "neutral", "moderate"),
        )
    conn.commit()
    conn.close()


def seed_test_doctors(default_password: str = "demo1234") -> None:
    """Seed additional review doctor accounts (idempotent INSERT only)."""
    doctors = [
        ("dr_review", "검토의사", "내분비내과", 15, "neutral", "moderate"),
        ("dr_kim",    "김내분비", "내분비내과",  8, "cautious", "conservative"),
    ]
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    password_hash = hash_password(default_password)
    for doctor_id, name, specialty, years, attitude, risk in doctors:
        cursor.execute("SELECT doctor_id FROM doctors WHERE doctor_id = ?", (doctor_id,))
        if not cursor.fetchone():
            cursor.execute(
                "INSERT INTO doctors (doctor_id, password_hash, name, specialty, years_experience, supplement_attitude, risk_tolerance) "
                "VALUES (?, ?, ?, ?, ?, ?, ?)",
                (doctor_id, password_hash, name, specialty, years, attitude, risk),
            )
    conn.commit()
    conn.close()

def hash_password(password: str) -> str:
    """Hash password using SHA-256."""
    return hashlib.sha256(password.encode()).hexdigest()

def create_access_token(user_id: str, name: str, role: str = "patient") -> str:
    """Create JWT access token."""
    expire = datetime.utcnow() + timedelta(minutes=ACCESS_TOKEN_EXPIRE_MINUTES)
    to_encode = {
        "sub": user_id,
        "name": name,
        "role": role,
        "exp": expire
    }
    encoded_jwt = jwt.encode(to_encode, SECRET_KEY, algorithm=ALGORITHM)
    return encoded_jwt


def decode_access_token(token: str) -> Optional[dict]:
    """Decode JWT token. Returns None for invalid/expired token."""
    try:
        return jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
    except jwt.PyJWTError:
        return None

def verify_token(credentials: HTTPAuthorizationCredentials = Depends(security)) -> dict:
    """Verify JWT token and return payload."""
    try:
        payload = jwt.decode(credentials.credentials, SECRET_KEY, algorithms=[ALGORITHM])
        return payload
    except jwt.ExpiredSignatureError:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Token has expired"
        )
    except jwt.InvalidTokenError:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid token"
        )

def register_patient(request: PatientRegisterRequest) -> TokenResponse:
    """Register a new patient."""
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    
    # Check if patient already exists
    cursor.execute("SELECT patient_id FROM patients WHERE patient_id = ?", (request.patient_id,))
    if cursor.fetchone():
        conn.close()
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Patient ID already exists"
        )
    
    # Insert new patient
    password_hash = hash_password(request.password)
    cursor.execute(
        "INSERT INTO patients (patient_id, password_hash, name, conditions, medications) VALUES (?, ?, ?, ?, ?)",
        (request.patient_id, password_hash, request.name, request.conditions, request.medications)
    )
    conn.commit()
    conn.close()
    
    # Create token
    token = create_access_token(request.patient_id, request.name, role="patient")
    return TokenResponse(
        access_token=token,
        token_type="bearer",
        patient_id=request.patient_id,
        name=request.name,
        role="patient"
    )

def login_patient(request: PatientLoginRequest) -> TokenResponse:
    """Login patient and return token."""
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    
    password_hash = hash_password(request.password)
    cursor.execute(
        "SELECT patient_id, name FROM patients WHERE patient_id = ? AND password_hash = ?",
        (request.patient_id, password_hash)
    )
    result = cursor.fetchone()
    conn.close()
    
    if not result:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid credentials"
        )
    
    patient_id, name = result
    token = create_access_token(patient_id, name, role="patient")
    return TokenResponse(
        access_token=token,
        token_type="bearer",
        patient_id=patient_id,
        name=name,
        role="patient"
    )

def get_patient_profile(patient_id: str) -> PatientProfile:
    """Get patient profile information."""
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    
    cursor.execute(
        "SELECT patient_id, name, conditions, medications, age, sex, health_literacy, preference_type, current_supplements, created_at FROM patients WHERE patient_id = ?",
        (patient_id,)
    )
    result = cursor.fetchone()
    conn.close()
    
    if not result:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Patient not found"
        )
    
    return PatientProfile(
        patient_id=result[0],
        name=result[1],
        conditions=result[2] or "",
        medications=result[3] or "",
        age=result[4],
        sex=result[5] or "female",
        health_literacy=result[6] or "general",
        preference_type=result[7] or "moderate",
        current_supplements=result[8] or "",
        created_at=result[9]
    )

def update_patient_profile(
    patient_id: str,
    name: Optional[str] = None,
    conditions: Optional[str] = None,
    medications: Optional[str] = None,
    age: Optional[int] = None,
    sex: Optional[str] = None,
    health_literacy: Optional[str] = None,
    preference_type: Optional[str] = None,
    current_supplements: Optional[str] = None,
) -> PatientProfile:
    """Update patient medical information."""
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()

    cursor.execute(
        "SELECT name, conditions, medications, age, sex, health_literacy, preference_type, current_supplements FROM patients WHERE patient_id = ?",
        (patient_id,),
    )
    existing = cursor.fetchone()
    if not existing:
        conn.close()
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Patient not found"
        )

    next_name = existing[0] if name is None else name
    next_conditions = existing[1] if conditions is None else conditions
    next_medications = existing[2] if medications is None else medications
    next_age = existing[3] if age is None else age
    next_sex = existing[4] if sex is None else sex
    next_literacy = existing[5] if health_literacy is None else health_literacy
    next_preference = existing[6] if preference_type is None else preference_type
    next_supplements = existing[7] if current_supplements is None else current_supplements

    cursor.execute(
        "UPDATE patients SET name=?, conditions=?, medications=?, age=?, sex=?, health_literacy=?, preference_type=?, current_supplements=? WHERE patient_id=?",
        (next_name, next_conditions, next_medications, next_age, next_sex, next_literacy, next_preference, next_supplements, patient_id)
    )
    conn.commit()
    conn.close()
    
    return get_patient_profile(patient_id)

def register_doctor(request: DoctorRegisterRequest) -> TokenResponse:
    """Register a new doctor."""
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    
    cursor.execute("SELECT doctor_id FROM doctors WHERE doctor_id = ?", (request.doctor_id,))
    if cursor.fetchone():
        conn.close()
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Doctor ID already exists"
        )
    
    password_hash = hash_password(request.password)
    cursor.execute(
        "INSERT INTO doctors (doctor_id, password_hash, name, specialty, years_experience, supplement_attitude, risk_tolerance) VALUES (?, ?, ?, ?, ?, ?, ?)",
        (request.doctor_id, password_hash, request.name, request.specialty, request.years_experience, request.supplement_attitude, request.risk_tolerance)
    )
    conn.commit()
    conn.close()
    
    token = create_access_token(request.doctor_id, request.name, role="doctor")
    return TokenResponse(
        access_token=token,
        token_type="bearer",
        doctor_id=request.doctor_id,
        name=request.name,
        role="doctor"
    )

def login_doctor(request: DoctorLoginRequest) -> TokenResponse:
    """Login doctor and return token."""
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    
    password_hash = hash_password(request.password)
    cursor.execute(
        "SELECT doctor_id, name FROM doctors WHERE doctor_id = ? AND password_hash = ?",
        (request.doctor_id, password_hash)
    )
    result = cursor.fetchone()
    conn.close()
    
    if not result:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid credentials"
        )
    
    doctor_id, name = result
    token = create_access_token(doctor_id, name, role="doctor")
    return TokenResponse(
        access_token=token,
        token_type="bearer",
        doctor_id=doctor_id,
        name=name,
        role="doctor"
    )

def get_doctor_profile(doctor_id: str) -> DoctorProfile:
    """Get doctor profile information."""
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    
    cursor.execute(
        "SELECT doctor_id, name, specialty, years_experience, supplement_attitude, risk_tolerance, created_at FROM doctors WHERE doctor_id = ?",
        (doctor_id,)
    )
    result = cursor.fetchone()
    conn.close()
    
    if not result:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Doctor not found"
        )
    
    return DoctorProfile(
        doctor_id=result[0],
        name=result[1],
        specialty=result[2],
        years_experience=result[3],
        supplement_attitude=result[4],
        risk_tolerance=result[5],
        created_at=result[6]
    )

def update_doctor_profile(doctor_id: str, specialty: str, years_experience: int, supplement_attitude: str, risk_tolerance: str) -> DoctorProfile:
    """Update doctor profile."""
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    
    cursor.execute(
        "UPDATE doctors SET specialty = ?, years_experience = ?, supplement_attitude = ?, risk_tolerance = ? WHERE doctor_id = ?",
        (specialty, years_experience, supplement_attitude, risk_tolerance, doctor_id)
    )
    conn.commit()
    conn.close()
    
    return get_doctor_profile(doctor_id)


def list_virtual_accounts(default_password: str = "demo1234") -> List[VirtualPatientAccount]:
    accounts: List[VirtualPatientAccount] = []
    for patient in _load_virtual_patients():
        patient_id = str(patient.get("id", "")).strip()
        if not patient_id:
            continue
        accounts.append(
            VirtualPatientAccount(
                patient_id=patient_id,
                name=str(patient.get("name") or patient.get("persona") or patient_id),
                conditions=", ".join(patient.get("conditions", []) or []),
                medications=", ".join(patient.get("medications", []) or []),
                default_password=default_password,
            )
        )
    return accounts

# Initialize database on module load
init_db()
seed_virtual_patients()
refresh_virtual_patient_profiles()
seed_demo_patient()
seed_doctors()
seed_test_doctors()
