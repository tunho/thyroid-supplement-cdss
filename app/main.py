"""
app.main — 갑상선 영양제 의사결정 지원 시스템 (슬림 배포 진입점)

배포본은 갑상선 의사결정 코어 + 프론트엔드만 포함한다.
대용량 RAG 인덱스/식약처 캐시(1GB+) 없이도 동작하도록, 일반 RAG 카탈로그
로드는 제외했다. 임상 판정은 결정론적 규칙 엔진이 담당하고, LLM은 판정 후
자연어 설명 생성에만 쓰인다.
"""
from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pathlib import Path
from app.api.v1.api import api_router
from dotenv import load_dotenv

load_dotenv()

RAG_APP_ROOT = Path(__file__).resolve().parent.parent
FRONT_DIR = RAG_APP_ROOT / "frontend"

app = FastAPI(title="Thyroid Supplement CDSS", version="2.0.0")


@app.exception_handler(Exception)
async def generic_exception_handler(request: Request, exc: Exception):
    import traceback
    traceback.print_exc()
    return JSONResponse(
        status_code=500,
        content={"detail": "Internal Server Error", "type": type(exc).__name__},
    )


app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

if FRONT_DIR.exists():
    app.mount("/static", StaticFiles(directory=str(FRONT_DIR)), name="static")


@app.get("/")
def read_root():
    index_file = FRONT_DIR / "index.html"
    if not index_file.exists():
        raise HTTPException(status_code=404, detail="index.html not found")
    return FileResponse(str(index_file))


@app.get("/health")
def health_check():
    return {"status": "ok"}


@app.get("/ready")
def readiness_check():
    # 슬림 배포는 백그라운드 카탈로그 로드가 없어 부팅 직후 ready.
    return {"ready": True}


# Include all API routes
app.include_router(api_router, prefix="/api")


if __name__ == "__main__":
    import os
    import uvicorn

    port = int(os.getenv("PORT", "8000"))
    uvicorn.run("app.main:app", host="0.0.0.0", port=port)
