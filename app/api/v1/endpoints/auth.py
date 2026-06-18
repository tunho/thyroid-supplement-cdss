from fastapi import APIRouter, Depends, HTTPException
from domain.auth.auth_service import (
    PatientLoginRequest,
    PatientRegisterRequest,
    DoctorLoginRequest,
    DoctorRegisterRequest,
    TokenResponse,
    PatientProfile,
    DoctorProfile,
    PatientUpdateProfileRequest,
    DoctorUpdateProfileRequest,
    register_patient,
    login_patient,
    get_patient_profile,
    update_patient_profile,
    register_doctor,
    login_doctor,
    get_doctor_profile,
    update_doctor_profile,
    verify_token,
    list_virtual_accounts,
)

router = APIRouter()

@router.post("/register", response_model=TokenResponse)
def auth_register(request: PatientRegisterRequest):
    """Register a new patient."""
    return register_patient(request)

@router.post("/login", response_model=TokenResponse)
def auth_login(request: PatientLoginRequest):
    """Login patient and return JWT token."""
    return login_patient(request)

@router.get("/profile", response_model=PatientProfile)
def auth_get_profile(token_data: dict = Depends(verify_token)):
    """Get current patient profile."""
    if token_data.get("role", "patient") != "patient":
        raise HTTPException(status_code=403, detail="Patient access required")
    patient_id = token_data.get("sub")
    if not patient_id:
        raise HTTPException(status_code=401, detail="Invalid token")
    return get_patient_profile(patient_id)

@router.get("/virtual-accounts")
def auth_virtual_accounts():
    """Demo virtual accounts for quick login tests."""
    return list_virtual_accounts()

@router.put("/profile", response_model=PatientProfile)
def auth_update_profile(
    request: PatientUpdateProfileRequest,
    token_data: dict = Depends(verify_token)
):
    """Update patient medical information."""
    if token_data.get("role", "patient") != "patient":
        raise HTTPException(status_code=403, detail="Patient access required")
    patient_id = token_data.get("sub")
    if not patient_id:
        raise HTTPException(status_code=401, detail="Invalid token")
    return update_patient_profile(
        patient_id,
        request.name,
        request.conditions,
        request.medications,
        request.age,
        request.sex,
        request.health_literacy,
        request.preference_type,
        request.current_supplements,
    )

@router.post("/doctor/register", response_model=TokenResponse)
def auth_doctor_register(request: DoctorRegisterRequest):
    """Register a new doctor."""
    return register_doctor(request)

@router.post("/doctor/login", response_model=TokenResponse)
def auth_doctor_login(request: DoctorLoginRequest):
    """Login doctor and return JWT token."""
    return login_doctor(request)

@router.get("/doctor/profile", response_model=DoctorProfile)
def auth_get_doctor_profile(token_data: dict = Depends(verify_token)):
    """Get current doctor profile."""
    if token_data.get("role", "patient") != "doctor":
        raise HTTPException(status_code=403, detail="Doctor access required")
    doctor_id = token_data.get("sub")
    if not doctor_id:
        raise HTTPException(status_code=401, detail="Invalid token")
    return get_doctor_profile(doctor_id)

@router.put("/doctor/profile", response_model=DoctorProfile)
def auth_update_doctor_profile(
    request: DoctorUpdateProfileRequest,
    token_data: dict = Depends(verify_token)
):
    """Update doctor profile preferences."""
    if token_data.get("role", "patient") != "doctor":
        raise HTTPException(status_code=403, detail="Doctor access required")
    doctor_id = token_data.get("sub")
    if not doctor_id:
        raise HTTPException(status_code=401, detail="Invalid token")
    return update_doctor_profile(
        doctor_id, 
        request.specialty, 
        request.years_experience, 
        request.supplement_attitude, 
        request.risk_tolerance
    )
