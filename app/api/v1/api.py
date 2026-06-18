from fastapi import APIRouter
from app.api.v1.endpoints import auth, feedback, thyroid

api_router = APIRouter()
api_router.include_router(auth.router, prefix="/auth", tags=["Auth"])

# ── Thyroid Decision Core (v1) ──
api_router.include_router(thyroid.router, prefix="/v1", tags=["Thyroid Decision Core"])

# ── Feedback (v1) ──
api_router.include_router(feedback.router, prefix="/v1/feedback", tags=["Feedback"])
