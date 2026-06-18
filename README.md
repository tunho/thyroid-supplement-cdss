# 갑상선 영양제 의사결정 지원 시스템 (Thyroid Supplement CDSS)

갑상선 질환자의 영양제 복용에 대해 **안전성·근거를 결정론적 규칙 엔진으로 판정**하고,
LLM(GPT-4o-mini)은 **판정 이후 자연어 설명 생성에만** 사용하는 임상 의사결정 지원 서비스입니다.

> 핵심 설계 원칙: **LLM은 임상 판정을 내리지 않는다.** 모든 판정(권고/조건부/회피/금기/근거부족)은
> 검증된 규칙·근거 테이블에 의해 결정론적으로 산출되어, 결과가 재현 가능하고 추적 가능합니다.

[![CI](https://github.com/tunho/thyroid-supplement-cdss/actions/workflows/ci.yml/badge.svg)](https://github.com/tunho/thyroid-supplement-cdss/actions/workflows/ci.yml)

- **배포 URL**: https://thyroid-supplement-cdss.onrender.com  *(Render 배포 후 확정)*
- **API 문서**: `<배포 URL>/docs` (Swagger UI)

---

## 주요 기능

- **환자용 상담** (`POST /api/v1/patient/thyroid-chat`): 부드러운 톤의 일반 정보 + 상담 유도
- **의사용 자문** (`POST /api/v1/doctor/thyroid-consult`): 실시간 PubMed 근거 + 구조화 판정
- **안전성 엔진**: 24개 카테고리 / 34개 규칙 (요오드 과잉, 식약처 상한, 임신, 레보티록신·항응고제 상호작용 등). CRITICAL 경고는 판정 전에 조기 차단(CONTRAINDICATED).
- **6-class 판정**: RECOMMEND / CONDITIONAL_CONSIDER / AVOID / CONTRAINDICATED / INSUFFICIENT_EVIDENCE
- **감사 로그**: 모든 판정을 JSONL로 기록 (`data/audit/`)

## 아키텍처

```
Request ─▶ PatientProfile ─▶ SafetyEngine ─▶ (CRITICAL? → CONTRAINDICATED)
                                   │
                                   ▼
                          PubMed 근거 검색(의사) ─▶ DecisionEngine ─▶ Formatter ─▶ Response + Audit
```

| 레이어 | 위치 |
|---|---|
| API (FastAPI) | `app/` — `app/api/v1/endpoints/thyroid.py`, `app/services/thyroid/orchestrator.py` |
| 결정 코어 | `domain/thyroid/` — `safety.py`, `decision.py`, `rules.py`, `response.py` |
| 공공데이터 | `domain/consultation/pubmed/` (PubMed), `domain/mfds/` (식약처) |
| 인증 | `domain/auth/` (JWT, SQLite) |
| 프론트엔드 | `frontend/` (정적 HTML/JS/CSS) |

## 기술 스택

Python 3.12 · FastAPI · Pydantic · SQLite · OpenAI GPT-4o-mini · PubMed E-utilities · 식약처(MFDS) API · Docker · Render · GitHub Actions

## 공공데이터

- **식약처(MFDS)**: 건강기능식품 상한섭취량(UL), 개별인정형 원료 주의사항
- **PubMed (NIH)**: 실시간 문헌 근거 검색·요약

---

## 로컬 실행

### Docker (권장)

```bash
docker build -t thyroid-cdss .
docker run --rm -p 8000:8000 -e OPENAI_API_KEY=sk-... thyroid-cdss
# http://localhost:8000
```

### 직접 실행

```bash
python -m venv venv && source venv/bin/activate
pip install -r requirements.txt
cp .env.example .env   # OPENAI_API_KEY 입력
PYTHONPATH=. uvicorn app.main:app --host 0.0.0.0 --port 8000
```

### 테스트 계정

서버 기동 시 자동 시드됩니다. 공통 비밀번호 `demo1234`. 자세한 목록은 [TEST_ACCOUNTS.md](TEST_ACCOUNTS.md).

### 테스트

```bash
PYTHONPATH=. pytest tests/test_thyroid_decision.py tests/test_thyroid_safety.py -v
```

---

## 배포 & CI/CD

- **CI** — GitHub Actions(`.github/workflows/ci.yml`): push/PR마다 규칙 로직 테스트 + 앱 import 스모크 테스트
- **CD** — Render Blueprint(`render.yaml`): `main` 브랜치 push 시 Docker 이미지 자동 빌드·재배포(`autoDeploy: true`)
- 배포 방법: Render 대시보드 → **New ▸ Blueprint** → 본 레포 선택 → `OPENAI_API_KEY` 입력 → Deploy

> 본 배포본은 **갑상선 의사결정 코어 + 프론트엔드**로 구성된 슬림 버전입니다.
> 일반 영양제 카탈로그 RAG 검색(대용량 인덱스 필요)은 제외되어 있으며, 핵심 임상 판정 기능은 모두 동작합니다.

## 면책

본 서비스는 정보 제공 및 의사결정 지원 목적이며, 의학적 진단·처방을 대체하지 않습니다. 실제 복용 결정은 반드시 전문의와 상담하십시오.
