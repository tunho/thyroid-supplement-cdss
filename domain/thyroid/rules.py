"""
domain.thyroid.rules — 갑상선 환자를 위한 MVP supplement rule 테이블

각 rule은 dict로 관리하며, DecisionEngine/SafetyEngine이 참조합니다.
테이블 수정만으로 판단 로직이 변경되도록 설계했습니다.
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional


# ──────────────────────────────────────────────────────────
# Rule 구조 타입 힌트 (dict 기반, 향후 Pydantic 전환 가능)
# ──────────────────────────────────────────────────────────
# {
#   "applicable_conditions":  List[str],  # 이 supplement가 도움될 수 있는 진단/상태
#   "possible_benefits":      List[str],  # 기대 효과
#   "avoid_conditions":       List[str],  # 피해야 하는 상태
#   "contraindications":      List[str],  # 절대 금기
#   "required_patient_info":  List[str],  # 판단에 필수인 환자 정보 필드
#   "evidence_level":         str,        # guideline / rct / observational / mechanistic / insufficient
#   "risk_tags":              List[str],  # iodine_excess, pregnancy, drug_interaction 등
#   "notes":                  str,        # 자유 형식 비고
# }


SUPPLEMENT_RULES: Dict[str, Dict[str, Any]] = {
    # ── Iodine ──────────────────────────────────────────
    "iodine": {
        "applicable_conditions": [
            "iodine_deficiency",                  # [WHO2007-IDD]
            "hypothyroidism_iodine_deficiency",
            "goiter_iodine_deficiency",           # [WHO2007-IDD]
            "pregnancy",                          # [ATA2017-R5, PMID:28056690] 임산부 250 µg/일 (Strong, high)
            "lactation",                          # [ATA2017-R81, PMID:28056690] 수유 250 µg/일 (Strong, high)
        ],
        "possible_benefits": [
            "갑상선 호르몬 합성에 필수 미량원소",                                   # [clinical-standard]
            "요오드 결핍 지역에서 갑상선종 예방",                                   # [WHO2007-IDD]
            "[임신/수유] 태아·영아 신경 발달과 갑상선 호르몬 합성에 중요",            # [ATA2017-R5] [ATA2017-R81]
        ],
        "avoid_conditions": [
            "graves_disease",            # [ATA2017-R9 — 임신 중 과도 노출 회피]
            "hyperthyroidism",
            "hashimoto",
            "autonomous_thyroid_nodule", # [ATA2016-Rec36, PMID:27521067] Jod-Basedow — 결절성 갑상선종 요오드 유발 항진증
            "subclinical_hyperthyroidism", # [C-등급·전문가검증필요] 과잉 요오드가 현성 항진 유발 위험 (자율성 동반 시 Jod-Basedow)
            "postpartum_thyroiditis",      # [C-등급·전문가검증필요] 자가면역 갑상선염 — 과잉 요오드 노출이 악화 가능 (예방효과 없음)
        ],
        "contraindications": [
            "iodine_allergy",         # [clinical-standard] 요오드 알레르기 — 표준 절대 금기(정의적)
            "active_hyperthyroidism", # [ATA2016-Rec36, PMID:27521067] 활성 항진증 — 요오드가 갑상선중독증 악화(Jod-Basedow)
        ],
        "required_patient_info": [
            "diagnosis",
            "lab_values.TSH",
            "medications",
            "lab_values.TPOAb",  # [ATA2017-R92] TPOAb 상태 — PPT 예방 평가
            "risk_factors",      # [ATA2017-R5] 임신·수유 상태 필수 (권장량 250 µg/일)
        ],
        "evidence_level": "guideline",  # [ATA2017] [WHO2007-IDD]
        "risk_tags": ["iodine_excess", "thyrotoxicosis_risk", "pregnancy_caution"],
        "notes": (
            "과량 섭취 시 갑상선 기능 항진 또는 억제 모두 유발 가능. "
            "하시모토/그레이브스 환자에서 추가 요오드 보충은 일반적으로 비권장. "
            "[결절성 갑상선종·자율성 결절] 과량 요오드는 요오드 유발 갑상선기능항진증(Jod-Basedow)을 "
            "유발할 수 있어 비권장 — 칼륨요오드(KI)는 일부 GD·수술 준비·갑상선폭풍에서 의사 처방 하 "
            "치료 목적으로만 사용 (ATA 2016 [I] Rec 36 No-rec/insufficient, TMNG·독성선종은 RAI/수술 Rec 37, Weak/moderate). "
            "[임신·수유] ATA 2017: 임신·수유 250 µg/일 권장, 500 µg/일 초과 지속 섭취 회피. "
            "WHO 권장 일일 섭취량: 성인 150 µg, 임산부 250 µg. "
            "[임신 TPOAb+] iodine 또는 LT4 로 산후 갑상선염(PPT) 예방 비효과적 — 권장 안 함 "
            "(ATA 2017 R92, Strong, high)."
        ),  # [ATA2017-R5] [ATA2017-R10] [ATA2017-R92] [ATA2016-Rec36, PMID:27521067] [ATA2016-Rec37] [WHO2007-IDD]
        "recommended_dose": (
            "[일반 성인 NIH ODS/WHO] 150 µg/일; "
            "[일반 성인 한국 KDRI 2025 권장섭취량] 150 µg/일 (NIH 일치); "
            "[임신 NIH ODS] 220 µg/일; "
            "[임신 한국 KDRI 2025 권장섭취량] 240 µg/일 (150+부가 90); "
            "[임신 ATA 2017] 250 µg/일 (R5, Strong, high) — 보수적 값 채택; "
            "[수유 NIH ODS] 290 µg/일; "
            "[수유 한국 KDRI 2020] 약 340 µg/일; "
            "[수유 ATA 2017] 250 µg/일 (R81, Strong, high); "
            "[임신 계획/임신/수유] 칼륨 요오드화물(KI) 형태 150 µg/일 보충, "
            "임신 3개월 전 시작 권장 (ATA 2017 R6, Strong, moderate); "
            "[한국 시장 표시량 통계] MFDS health_food DB 중앙값 150 µg (N=34건, 범위 45~1,000 µg)"
        ),  # [ATA2017-R5] [ATA2017-R6] [ATA2017-R81] [NIH-ODS-Iodine] [KDRI2025] [WHO2007-IDD] [MFDS-health_food-stats]
        "study_dose": (
            "[임신] ATA 2017 250 µg/일 — 7000명 중국 임산부 연구 기반 (PMID:28056690 R5); "
            "[수유] 250 µg/일 (R81); "
            "[임신 계획] KI 150 µg/일 × 임신 3개월 전 (R6); "
            "[저자원 지역] iodized oil 400 mg/년 1회 대안 (R7, Weak, moderate)"
        ),  # [ATA2017-R5] [ATA2017-R6] [ATA2017-R7] [ATA2017-R81]
        "official_upper_limit": (
            "[성인 NIH ODS UL] 1,100 µg/일; "
            "[성인 한국 MFDS UL] 2,400 µg/일 — 기관 간 큰 차이; "
            "[WHO 안전 기준] 500 µg/일; "
            "[임신 ATA 2017] 500 µg/일 초과 지속 섭취 회피 (R10, Strong, moderate); "
            "[수유 ATA 2017] 500~1,100 µg/일 초과 지속 회피 — 영아 갑상선 기능 저하 가능 "
            "(R84, Strong, moderate); "
            "[임신·수유] 잠정 정책: 보수적 값 채택 — 임신/수유 시 ATA 500 µg/일 기준 우선 적용"
        ),  # [ATA2017-R10] [ATA2017-R84] [NIH-ODS-Iodine] [KDRI2025] [MFDS2023] [WHO2007-IDD]
        "counseling_points": [
            "[임신 계획/임신/수유] 칼륨 요오드화물 형태 150 µg/일 보충, 임신 3개월 전 시작",     # [ATA2017-R6]
            "[수유] 다시마·해조류는 요오드 함량 일관성 없음 — 정량 보충제 권장",                 # [ATA2017-R82]
            "[갑상선 항진증 치료 중 / LT4 복용 여성] 요오드 추가 보충 불필요",                  # [ATA2017-R8]
            "[임신] 과도한 요오드 노출 회피 — GD 수술 준비 예외",                            # [ATA2017-R9]
            "[저자원 지역] 출산 후 또는 임신 중 iodized oil 400 mg/년 1회 대안 (장기 전략 X)", # [ATA2017-R7] [ATA2017-R83]
            "[하시모토/기능저하증] 소량(150 µg/일 이내) 일반적 허용 — 과잉 주의",               # [NIH-ODS-Iodine] [WHO2007-IDD]
            "[메티마졸/PTU 복용 중] 요오드는 갑상선 기능을 양방향(Wolff-Chaikoff 억제 / Jod-Basedow 항진, escape 현상)으로 흔들 수 있어 섭취 변화 시 약물 효과에 영향 가능 — 처방의 확인 (기전 ATA 2016 [I])",  # [ATA2016-Rec36, PMID:27521067]
            "[다시마·해조류 일반] 제품마다 요오드 함량 수십~수천 µg 불규칙 — 임상 별도 취급",    # [clinical-standard]
            "[결절성 갑상선종·자율성 결절] 요오드 보충제·다시마는 Jod-Basedow(요오드 유발 항진증) 위험 — 회피 (ATA 2016 Rec 36)",  # [ATA2016-Rec36, PMID:27521067]
            "[갑상선암 RAI 치료 준비] 저요오드식(≤50µg/일) 1~2주 — 요오드 보충제·다시마·해조류·요오드 조영제 회피 (ATA 2015 Rec 57, Weak/low)",  # [ATA2015-Rec57, PMID:26462967]
            "[갑상선 항진증 수술 준비 예외] potassium iodide 50~100 mg/일 × 7~10일 — 의사 처방 하에서만 (ATA 2017 R46d, Weak, low)",  # [ATA2017-R46d, PMID:28056690]
        ],
        "monitoring_parameters": [
            "TSH, Free T4, Free T3 — 요오드 섭취량 변경 후",                                # [clinical-standard]
            "항갑상선항체 (TPOAb, TRAb) — 자가면역 갑상선 질환 시",                          # [clinical-standard]
            "[인구 집단 수준] 소변 요오드 — 개인 영양 상태 마커로 부적합 (ATA 2017 R4)",       # [ATA2017-R4]
            "[TPOAb+ 임신] 매 4주 TSH 측정 — 임신 중반(16~20주)까지, 이후 24~28주 1회 (ATA 2017 R11, Strong, high)",  # [ATA2017-R11, PMID:28056690]
            "[TPOAb+ TSH > 2.5 mIU/L 임신] LT4 시작 고려 (ATA 2017 R29, Weak, moderate)",                              # [ATA2017-R29, PMID:28056690]
        ],
    },

    # ── Selenium ─────────────────────────────────────────
    "selenium": {
        "applicable_conditions": [
            "hashimoto",
            "graves_orbitopathy",      # [EUGOGO2021-Rec7, PMID:34297684] [ATAETA2022-KP6.1.1, PMID:36480280]  (legacy PMID:21525463 오기 제거 — 무관 논문)
            "autoimmune_thyroiditis",
            "selenium_deficiency",
        ],
        "possible_benefits": [
            "[하시모토] 갑상선 과산화효소 항체(TPOAb) 감소",            # [Gartner2002, PMID:11932302]
            "[그레이브스 안병증] 경증·활동성·최근 발병 그레이브스 안병증 개선 — 중등도-중증엔 근거 없음 (EUGOGO 2021 Rec #7 / 2022 ATA/ETA TED KP6.1.1)",  # [EUGOGO2021-Rec7, PMID:34297684] [ATAETA2022-KP6.1.1, PMID:36480280] [Marcocci2011, PMID:21591944]
            "산화 스트레스 감소",                                    # [clinical-standard]
        ],
        "avoid_conditions": [
            "selenium_toxicity_history",  # [NIH-ODS-Selenium]
            "renal_failure_severe",
        ],
        "contraindications": [
            "known_selenium_hypersensitivity",  # [clinical-standard] 셀레늄 과민증 — 표준 절대 금기(정의적)
        ],
        "required_patient_info": [
            "diagnosis",
            "lab_values.selenium",
            "lab_values.TPOAb",       # [ATA2017-R12] TPOAb 상태 — 임신 시 보충 평가
            "risk_factors",           # [ATA2017-R12] 임신·수유 상태
        ],
        "evidence_level": "rct",  # [EUGOGO2021-Rec7, PMID:34297684] [Marcocci2011, PMID:21591944]
        "risk_tags": ["selenium_toxicity", "pregnancy_caution"],
        "notes": (
            "200µg/일(원소 셀레늄)은 갑상선 보조 연구의 보수적 운용상한이며 독성 역치가 아님 — "
            "공식 상한섭취량(UL)은 400µg/일(NIH ODS·KDRI 2025); 초과·장기 복용 시 총 섭취량 확인·selenosis 모니터링. "
            "[경증·활동성·최근 발병 그레이브스 안병증] sodium selenite 200µg/일(=원소 셀레늄 91.2µg) "
            "또는 selenomethionine 100µg/일 × 6개월 보충 권장 — 안구증상·삶의질 개선, "
            "중증 진행 예방, 중단 후 6개월까지 효과 유지 (EUGOGO 2021 Rec #7, Strong/low, "
            "근거 Marcocci 2011 NEJM RCT). 셀레늄 결핍 지역에서 입증, 충족 지역 효과 미확인. "
            "[그레이브스 안병증] 중등도-중증 GO엔 보조 효과 근거 없음. "
            "[그레이브스 안병증] 2022 ATA/ETA TED 합의문도 동일 regimen(selenite 100µg ×2/일 × 6개월)을 재확인하되 "
            "'may be considered'로 보다 신중한 어조 — 셀레늄 결핍 지역 한정 (Key Point 6.1.1). "
            "[하시모토] TPOAb 감소 관찰되나 TSH 개선 근거는 제한적. "
            "[임신 TPOAb+] selenium 보충 권장 안 함 — "
            "단일 연구 Negro 2007 (PMID:17284630) 미검증, 제2형 당뇨 위험 증가 보고 "
            "(ATA 2017 R12, Weak, moderate). "
            "[임신 갑상선 Ab+] iodine 또는 LT4 로 산후 갑상선염(PPT) 예방 비효과적 "
            "(ATA 2017 R92, Strong, high)."
        ),  # [EUGOGO2021-Rec7, PMID:34297684] [ATAETA2022-KP6.1.1, PMID:36480280] [Marcocci2011, PMID:21591944] [ATA2017-R12, PMID:28056690] [Negro2007, PMID:17284630] [ATA2017-R92]
        "recommended_dose": (
            "[일반 성인 NIH ODS RDA] 55 µg/일; "
            "[임신 NIH ODS] 60 µg/일; "
            "[수유 NIH ODS] 70 µg/일; "
            "[한국 KDRI 2025 권장섭취량] 성인 60 µg/일, 임신 +4(64), 수유 +10(70); "
            "[갑상선 질환 임상 관행] 100~200 µg/일 (원소 셀레늄, 200 µg 초과 금지); "
            "[경증·활동성 GO 6개월 한시] sodium selenite 200µg/일(=원소 91.2µg) 또는 "
            "selenomethionine 100µg/일 (EUGOGO 2021 Rec #7, 2022 ATA/ETA TED KP6.1.1 재확인); "
            "[한국 시장 표시량 통계] MFDS health_food DB 중앙값 55 µg (N=245건, 범위 0.055~200 µg)"
        ),  # [NIH-ODS-Selenium] [KDRI2025] [EUGOGO2021-Rec7, PMID:34297684] [ATAETA2022-KP6.1.1, PMID:36480280] [MFDS-health_food-stats]
        "study_dose": (
            "[그레이브스 안병증] Marcocci 2011 NEJM RCT (경증 GO, N=159): sodium selenite 200 µg/일 "
            "(원소 셀레늄 91.2 µg) × 6개월 — selenomethionine 100 µg/일은 국가 사정에 따른 대체 (EUGOGO 2021); "
            "[하시모토] RCT 다수: 100~200 µg/일 × 3~12개월; "
            "[그레이브스 안병증] 2022 ATA/ETA TED 합의문: selenium selenite 100µg ×2/일 × 6개월 (Key Point 6.1.1, 동일 regimen 재확인)"
        ),  # [Marcocci2011, PMID:21591944] [EUGOGO2021-Rec7, PMID:34297684] [ATAETA2022-KP6.1.1, PMID:36480280]
        "official_upper_limit": (
            "[일반 성인 NIH ODS UL] 400 µg/일 (임신·수유 동일); "
            "[한국 KDRI 2025 상한섭취량] 400 µg/일 (임신·수유 동일); "
            "[갑상선 임상 연구 관행] 200 µg/일 이하 — UL보다 보수적 적용; "
            "잠정 정책: 보수적 값 200 µg/일 우선"
        ),  # [NIH-ODS-Selenium] [KDRI2025] [MFDS2023]
        # counseling_points/monitoring_parameters: EUGOGO 2021 Rec #7 + ATA 2017 R11/R29 로 해소 (2026-05-30 7차)
        "counseling_points": [
            "일일 200µg(원소 셀레늄)은 갑상선 연구상 보수적 운용상한 — 공식 상한섭취량(UL)은 400µg/일(NIH ODS·KDRI 2025); 초과·장기 복용 시 총 섭취량 확인 및 selenosis(탈모·손톱 변형·소화기) 징후 모니터링",  # [NIH-ODS-Selenium] [KDRI2025]
            "selenomethionine 형태가 흡수율 높음",
            "3개월 이상 복용 후 TPOAb 변화 평가",
            "신부전 환자에서 용량 감량 고려",
            "[경증·활동성 그레이브스 안병증] sodium selenite 200µg(원소 91µg) 또는 selenomethionine 100µg, 6개월 한시 — 공복 복용 (EUGOGO 2021 Rec #7, Strong/low)",  # [EUGOGO2021-Rec7, PMID:34297684] [Marcocci2011, PMID:21591944]
            "[지역 단서] 셀레늄 충족(비결핍) 지역에서는 안병증 보충 효과 미확인 — 한국인 셀레늄 영양상태 확인 후 적용 권고",  # [EUGOGO2021-Rec7, PMID:34297684]
        ],
        "monitoring_parameters": [
            "TPOAb, TgAb — 3개월 간격",
            "TSH, Free T4",
            "혈중 셀레늄 (장기 복용·고용량 시)",
            "[그레이브스 안병증] 안과 CAS 점수",
            "[경증·활동성 GO 보충 시] 6개월 코스 전후 CAS·GO-QoL 재평가 — 중등도-중증 진행 시 면역억제 전환 (EUGOGO 2021 Rec #7/#8)",  # [EUGOGO2021-Rec7, PMID:34297684]
            "[TPOAb+ 임신] 매 4주 TSH 측정 — 임신 중반(16~20주)까지, 이후 24~28주 1회 (ATA 2017 R11, Strong, high)",  # [ATA2017-R11, PMID:28056690]
            "[TPOAb+ TSH > 2.5 mIU/L 임신] LT4 시작 고려 (ATA 2017 R29, Weak, moderate)",                              # [ATA2017-R29, PMID:28056690]
        ],
    },

    # ── Iron ──────────────────────────────────────────────
    "iron": {
        "applicable_conditions": [
            "hypothyroidism",
            "iron_deficiency",
            "iron_deficiency_anemia",
            "thyroidectomy_postop",
        ],
        "possible_benefits": [
            "갑상선 호르몬 합성에 필요한 갑상선 과산화효소(TPO)의 보조인자",
            "[LT4 복용] 철분 결핍 시 레보티록신 효과 감소 보정",
        ],
        "avoid_conditions": [
            "hemochromatosis",
            "iron_overload",
        ],
        "contraindications": [
            "hemochromatosis",
        ],
        "required_patient_info": ["diagnosis", "lab_values.ferritin", "medications"],
        "evidence_level": "observational",
        "risk_tags": ["drug_interaction", "levothyroxine_timing"],
        "notes": (
            "[LT4 복용] ferrous sulfate 는 레보티록신 흡수를 저해 — 동시 복용 시 TSH 상승 보고(1.6→5.4 mIU/L). "
            "[LT4 복용] 레보티록신과 시간 간격을 두어 복용 권장하되, 4시간 분리는 전통적 관행으로 대조시험 미검증 "
            "(ATA 2014 Q3b, Weak/weak). "
            "ferritin 검사 없이 경험적 보충은 과부하 위험. "
            "[LT4 복용] 갑상선기능저하증 + 철결핍 환자에서 레보티록신 반응 개선 보고. "
            "[위축성 위염·셀리악(하시모토 동반 多)] 철 흡수 저하 + LT4 필요량 증가 — 예상보다 높은 "
            "LT4 용량 시 H. pylori 위염·위축성 위염·셀리악 평가 권고 (ATA 2014 Q3c, Strong/moderate)."
        ),  # [ATA2014-Q3b, PMID:25266247] [ATA2014-Q3c]
        "recommended_dose": (
            "[일반 성인 남 NIH ODS RDA] 8 mg/일; "
            "[일반 성인 여 19-50 NIH ODS RDA] 18 mg/일; "
            "[성인 여 51+ NIH ODS RDA] 8 mg/일; "
            "[임신 NIH ODS RDA] 27 mg/일; "
            "[수유 NIH ODS RDA] 9 mg/일; "
            "[한국 KDRI 2025 권장섭취량] 성인 남 8 / 여 19-49 12 / 여 50-64 7 mg/일, 임신 +9; "
            "[일반 결핍 치료] elemental iron 100~200 mg/일; "
            "[레보티록신 복용 시] 4시간 간격 권장 (전통적 관행, ATA 2014 Q3b); "
            "[한국 시장 표시량 통계] MFDS health_food DB 중앙값 8.9 mg (N=129건, 범위 0.16~45 mg)"
        ),  # [NIH-ODS-Iron] [KDRI2025] [MFDS-health_food-stats]
        "study_dose": (
            "[LT4 복용] 레보티록신-철분 흡수 상호작용: ferrous sulfate 동시 복용 시 TSH 상승 보고"
            "(1.6→5.4 mIU/L, ATA 2014 Q3b 인용 연구); "
            "일반적 결핍 치료: elemental iron 기준 100~200 mg/일"
        ),  # [ATA2014-Q3b, PMID:25266247] [clinical-standard] 결핍 치료 용량
        "official_upper_limit": (
            "[성인 NIH ODS UL] 45 mg/일 (elemental iron, 임신·수유 동일); "
            "[한국 KDRI 2025 상한섭취량] 45 mg/일 (임신·수유 동일)"
        ),  # [NIH-ODS-Iron] [KDRI2025] [MFDS2023]
        # counseling/monitoring: ATA 2014 Q3a/Q3b 로 해소 (2026-05-30 9차)
        "counseling_points": [
            "[레보티록신 타이밍] 식전 60분 또는 취침 시(저녁식사 3시간 후) 일관 복용 — 일관성이 흡수 변동을 줄임 (ATA 2014 Q3a, Weak/moderate)",  # [ATA2014-Q3a, PMID:25266247]
            "[LT4 복용] 레보티록신은 아침 공복에 물과 함께 단독 복용 — 철분제와 같은 시간 복용 금지",
            "[LT4 복용] 레보티록신과 시간 간격 유지 (4시간은 전통적 관행)",
            "[종합비타민 주의] 철·칼슘 함유 종합비타민도 LT4 흡수를 저해할 수 있어 시간 분리 (ATA 2014 Q3b)",  # [ATA2014-Q3b, PMID:25266247]
            "비타민 C 또는 오렌지주스와 함께 복용 시 흡수 향상",
            "칼슘제·제산제·우유·커피·차와 동시 복용 피하기",
            "[LT4 복용] 위장장애(구역·변비) 시 식후 복용 가능 — 레보티록신과 간격은 반드시 유지",
            "흑색변은 철분 복용 시 정상 반응 — 선홍색 출혈·지속 복통 시 확인 필요",
        ],
        "monitoring_parameters": [
            "TSH, Free T4 — 철분 보충 시작 4~8주 후",
            "혈청 페리틴, 혈청철, TIBC",
            "CBC (Hb, MCV, MCH)",
        ],
    },

    # ── Vitamin D ─────────────────────────────────────────
    "vitamin_d": {
        "applicable_conditions": [
            "hypothyroidism",
            "hashimoto",
            "thyroid_cancer",          # [ATA2015, PMID:26462967] TSH 억제 골건강 — 수술전후 포함
            "thyroid_cancer_postop",
            "vitamin_d_deficiency",
        ],
        "possible_benefits": [
            "면역 조절 — 자가면역 갑상선염 환자에서 항체 감소 가능",
            "[갑상선 절제술 후] 칼슘 대사 보조",
            "[LT4 복용] 골다공증 예방 (레보티록신 장기 고용량 환자)",
        ],
        "avoid_conditions": [
            "hypercalcemia",
            "granulomatous_disease",
            # 원발성 부갑상선항진증 — 고칼슘혈증 악화 위험 (NIH-ODS Vitamin D: hypercalcemia/PHPT 주의)
            "primary_hyperparathyroidism",
        ],
        "contraindications": [
            "severe_hypercalcemia",
        ],
        "required_patient_info": ["diagnosis", "lab_values.25OH_vitD", "lab_values.calcium"],
        "evidence_level": "observational",
        "risk_tags": ["pregnancy_caution", "hypercalcemia_risk"],
        "notes": (
            "25(OH)D < 20ng/mL이면 대부분의 가이드라인에서 보충 권장. "
            "[하시모토] 비타민D 보충 후 TPOAb 감소 일부 관찰 (관찰연구 수준). "
            "고칼슘혈증 모니터링 필요. "
            "[갑상선암 수술 후 + 임신] TSH 억제 요법 유지 가능 — 골밀도 모니터링 중요 "
            "(ATA 2017 R66, R73, Weak, low). [갑상선암 TSH 억제 + 폐경 전후 골소실 위험] "
            "칼슘·비타민D 보조 ± 골강화제(비스포스포네이트·데노수맙 등) 고려 (ATA 2015 DTC, Weak). "
            "기존 safety rule `tsh_suppressed_bone_risk` 와 시너지."
        ),  # [ATA2017-R66, ATA2017-R73, PMID:28056690] [ATA2015, PMID:26462967]
        "recommended_dose": (
            "[일반 성인 19-70 NIH ODS RDA] 15 µg/일 (600 IU); "
            "[성인 70+ NIH ODS RDA] 20 µg/일 (800 IU); "
            "[임신 NIH ODS RDA] 15 µg/일 (600 IU); "
            "[수유 NIH ODS RDA] 15 µg/일 (600 IU); "
            "[한국 KDRI 2025 충분섭취량] 성인 19-64 10 µg/일(400 IU), 65+ 15 µg/일(600 IU), 임신·수유 +0; "
            "[임상 관행] 1,000~4,000 IU/일 (결핍 시 2,000~5,000 IU/일, 25(OH)D 모니터링); "
            "[한국 시장 표시량 통계] MFDS health_food DB 중앙값 10 µg/400 IU (N=2,607건, 범위 1.25~1,000 µg)"
        ),  # [NIH-ODS-VitaminD] [KDRI2025] [MFDS-health_food-stats]
        "official_upper_limit": (
            "[성인 NIH ODS UL] 100 µg/일 (4,000 IU, 임신·수유 동일); "
            "[한국 KDRI 2025 상한섭취량] 100 µg/일 (4,000 IU, 임신·수유 동일); "
            "[Endocrine Society 지침] 치료 목적 단기 고용량 50,000 IU/주 별도 허용 — 기관별 상이"
        ),  # [NIH-ODS-VitaminD] [KDRI2025] [MFDS2023] [Endocrine-Society-VitD2011]
        "counseling_points": [
            # 레보티록신 흡수 상호작용: ATA 2014 Q3b 간섭 목록에 비타민D 없음으로 해소 (2026-05-30 9차)
            "지용성 비타민 — 지방 함유 식사와 함께 복용 시 흡수 증가",
            "25(OH)D 20ng/mL 미만 시 보충 일반적으로 권고 (30ng/mL 기준 적용 기관도 있음)",
            "고용량(4000IU/일 초과) 장기 복용 시 혈청 칼슘 상승 모니터링",
            "신장 질환자: 활성형 전환 장애 가능 — 별도 처방 비타민D(calcitriol) 필요 여부 확인",
            "[LT4 복용] 비타민D는 ATA 2014 의 레보티록신 흡수 간섭 물질 목록(칼슘·철·담즙산결합제·제산제 등)에 포함되지 않음 — 일상 용량에서 간격 권고 근거 없음 (ATA 2014 Q3b)",  # [ATA2014-Q3b, PMID:25266247]
        ],
        "monitoring_parameters": [
            "25-OH 비타민D — 보충 시작 8~12주(2~3개월) 후 재측정 (목표 25(OH)D ≥20 ng/mL, 기관별 ≥30 적용)",  # [Endocrine-Society-VitD2011] [NIH-ODS-VitaminD]
            "혈청 Ca, P — 고용량 복용 또는 신기능 저하 시",
            "TSH, Free T4 — 갑상선 기능 추적",
            "신기능 (creatinine, eGFR) — 장기 고용량 복용 시",
        ],
    },

    # ── Multivitamin ──────────────────────────────────────
    "multivitamin": {
        "applicable_conditions": [
            "hypothyroidism",
            "thyroid_cancer_postop",
        ],
        "possible_benefits": [
            "기초 영양 보충 및 대사 기능 유지",
            "전반적인 활력 증진",
        ],
        "avoid_conditions": [
            "hyperthyroidism",
            "graves_disease",
        ],
        "contraindications": [],
        "required_patient_info": ["diagnosis", "medications"],
        "evidence_level": "expert_opinion",
        "risk_tags": ["iodine_caution", "drug_interaction"],
        "notes": (
            "[갑상선 항진] 대부분의 종합비타민에는 요오드(Iodine)가 포함되어 있어 갑상선기능항진증 환자에게 호르몬 교란을 일으킬 수 있습니다. "
            "[LT4 복용] 또한 칼슘, 철분 등 미네랄 성분이 레보티록신 흡수를 방해할 수 있어 약과 시간 간격(전통적으로 4시간)을 두는 것이 권장됩니다. "
            "반드시 무요오드(Iodine-free) 제품인지 함량을 확인하시기 바랍니다."
        ),  # [ATA2014-Q3b, PMID:25266247]
        "recommended_dose": "제품별 1일 권장량 준수 (요오드 함량 주의)",
    },

    # ── Zinc ──────────────────────────────────────────────
    "zinc": {
        "applicable_conditions": [
            "hypothyroidism",
            "zinc_deficiency",
        ],
        "possible_benefits": [
            "갑상선 호르몬 대사(T4→T3 전환)에 관여하는 미량원소",
            "면역 기능 보조",
        ],
        "avoid_conditions": [
            "copper_deficiency",
        ],
        "contraindications": [],
        "required_patient_info": ["diagnosis", "lab_values.zinc"],
        "evidence_level": "mechanistic",
        "risk_tags": ["drug_interaction", "levothyroxine_timing", "copper_depletion"],
        "notes": (
            "[LT4 복용] 아연은 ATA 2014 레보티록신 흡수 간섭 명시 목록(칼슘·철·담즙산결합제·제산제 등)에 "
            "포함되지 않음 — 다가양이온으로서 흡수 영향은 이론적 수준이며 철·칼슘만큼의 직접 근거는 제한적. "
            "보수적으로 2~4시간 분리 권장. "
            "장기 고용량 복용 시 구리 결핍 위험. "
        ),  # [ATA2014-Q3b, PMID:25266247]
        "recommended_dose": (
            "[일반 성인 남 NIH ODS RDA] 11 mg/일; "
            "[일반 성인 여 NIH ODS RDA] 8 mg/일; "
            "[임신 NIH ODS RDA] 11 mg/일; "
            "[수유 NIH ODS RDA] 12 mg/일; "
            "[한국 KDRI 2025 권장섭취량] 성인 남 10 / 여 8 mg/일, 임신 +2.5, 수유 +5.0; "
            "[임상 관행] 8~25 mg/일; "
            "[레보티록신 복용 시] 4시간 간격; "
            "[한국 시장 표시량 통계] MFDS health_food DB 중앙값 8.5 mg (N=750건, 범위 0.3~30 mg)"
        ),  # [NIH-ODS-Zinc] [KDRI2025] [MFDS-health_food-stats]
        "official_upper_limit": (
            "[성인 NIH ODS UL] 40 mg/일 (임신·수유 동일); "
            "[한국 KDRI 2025 상한섭취량] 35 mg/일 (임신·수유 동일)"
        ),  # [NIH-ODS-Zinc] [KDRI2025] [MFDS2023]
        "counseling_points": [
            # 레보티록신 흡수 방해 근거는 calcium/iron 보다 약함 (간격 권고는 보수적 적용)
            "[LT4 복용] 레보티록신과 동시 복용 시 흡수 감소 가능 — 간격 조정 여부 전문가 확인 권고",
            "40mg/일 초과 장기 복용 시 구리(copper) 결핍 위험 — 구리 보충 병행 고려",
            "공복 복용 시 흡수 좋으나 구역감 발생 가능 — 식후 복용도 허용",
            "상한: NIH 기준 40mg/일 (성인)",
            "과잉 증상: 구역, 구토, 두통 — 해당 시 복용량 감량 후 확인",
        ],
        "monitoring_parameters": [
            "TSH, Free T4 — 갑상선 기능 추적",
            # 혈청 zinc 측정은 결핍 의심 시 보조적
            "혈청 zinc 수치 — 필요 시 (결핍 의심 시)",
            "혈청 구리 (copper) — 장기 고용량(40mg 초과) 복용 시",
            "CBC — 구리 결핍 관련 빈혈 여부",
        ],
    },

    # ── Magnesium ─────────────────────────────────────────
    "magnesium": {
        "applicable_conditions": [
            "hypothyroidism",
            "magnesium_deficiency",
            "muscle_cramps_thyroid",
        ],
        "possible_benefits": [
            # "갑상선 호르몬 대사 보조인자" — 깨끗한 1차 출처 미확보(mechanistic 가설 수준)로 삭제 (2026-06-02)
            "[MFDS 인정 기능성] 신경·근육 기능 유지에 도움",  # [MFDS-health_food_ingredient] 식약처 고시 기능성
        ],
        "avoid_conditions": [
            "renal_failure_severe",
            "hypermagnesemia",
        ],
        "contraindications": [
            "severe_renal_failure_unmonitored",
        ],
        "required_patient_info": ["diagnosis", "lab_values.magnesium", "medications"],
        "evidence_level": "mechanistic",
        "risk_tags": ["drug_interaction", "levothyroxine_timing", "renal_caution"],
        "notes": (
            "[LT4 복용] 레보티록신과 동시 복용 시 흡수 간섭 가능 — 최소 4시간 간격. "
            "신기능 저하 환자에서 고마그네슘혈증 위험. "
        ),
        "recommended_dose": (
            "[일반 성인 남 19-30 NIH ODS RDA] 400 mg/일; "
            "[일반 성인 여 19-30 NIH ODS RDA] 310 mg/일; "
            "[성인 남 31+ NIH ODS RDA] 420 mg/일; "
            "[성인 여 31+ NIH ODS RDA] 320 mg/일; "
            "[임신 NIH ODS RDA] 350~360 mg/일 (연령별); "
            "[수유 NIH ODS RDA] 310~320 mg/일; "
            "[한국 KDRI 2025 권장섭취량] 성인 남 360~380 / 여 280 mg/일, 임신 +40; "
            "[임상 관행] 200~400 mg/일 (elemental magnesium); "
            "[레보티록신 복용 시] 4시간 간격; "
            "[한국 시장 표시량 통계] MFDS health_food DB 중앙값 100 mg (N=169건, 범위 7~510 mg)"
        ),  # [NIH-ODS-Magnesium] [KDRI2025] [MFDS-health_food-stats]
        "official_upper_limit": (
            "[성인 NIH ODS UL 보충제 기준] 350 mg/일 (식이 마그네슘 UL 미적용, 임신·수유 동일); "
            "[한국 KDRI 2025 상한섭취량] 350 mg/일 (식품외 급원 기준, 임신·수유 동일)"
        ),  # [NIH-ODS-Magnesium] [KDRI2025] [MFDS2023]
        # counseling/monitoring: NIH ODS(UL·독성·신기능) + LT4-Mg 흡수저해 증례로 출처 확정분만 추가.
        # benefit hedge(갑상선 호르몬 대사 보조인자 등)는 깨끗한 출처 미확보로 보류.
        "counseling_points": [
            "[LT4 복용] 마그네슘 함유 제산제·완하제(산화·수산화마그네슘)는 레보티록신 흡수를 저해해 TSH 상승을 유발한 증례 보고 — 최소 4시간 간격 + TSH 모니터링 (증례·in vitro 수준, 영양보충 용량의 직접 근거는 제한적)",  # [LT4-Mg case reports]
            "고용량(보충제 UL 350 mg/일 초과) 시 설사 등 위장 증상 — 분할 복용·감량 고려",  # [NIH-ODS-Magnesium]
            "신기능 저하·만성신질환자: 고마그네슘혈증 위험 — 복용 전 상담",  # [NIH-ODS-Magnesium]
        ],
        "monitoring_parameters": [
            "[LT4 복용] TSH, Free T4 — 마그네슘 함유 제산제·완하제 병용 또는 복약 패턴 변경 후",  # [LT4-Mg case reports]
            "신기능 (creatinine, eGFR)·혈청 마그네슘 — 신기능 저하 또는 고용량 복용 시",  # [NIH-ODS-Magnesium]
            "고마그네슘혈증 징후 — 설사·오심·복부경련(고용량), 저혈압·서맥/부정맥(독성)",  # [NIH-ODS-Magnesium]
        ],
    },

    # ── Probiotics ────────────────────────────────────────
    "probiotics": {
        "applicable_conditions": [
            "hashimoto",
            "hypothyroidism",
            "gut_dysbiosis",
        ],
        "possible_benefits": [
            "장-갑상선 축(gut-thyroid axis) 조절 가설",
            "면역 조절 보조",
        ],
        "avoid_conditions": [
            "immunocompromised_severe",
            "short_bowel_syndrome",
        ],
        "contraindications": [],
        "required_patient_info": ["diagnosis"],
        "evidence_level": "mechanistic",
        "risk_tags": ["insufficient_evidence"],
        "notes": (
            "기전적 근거(gut-thyroid axis)는 있으나 임상 권고로 연결되지 않음. "
            "[LT4 복용] 레보티록신 흡수를 임상적으로 저해한다는 직접 근거는 제한적이며, "
            "흡수 개선 효과도 확립되지 않음 — 흡수 영향은 중립적으로 해석. "
            "면역억제 환자에서 생균 감염 위험."
        ),
        "recommended_dose": (
            "[일반] CFU 10억~1000억/일; 제품별 다양한 균주 성분 확인 권장; "
            "[NIH ODS] RDA/UL 미설정 (Fact Sheet 미발행); "
            "[한국 MFDS 인정 기능성원료] daily_intake 다양 — 균주별 별도 (예: "
            "Bacillus coagulans SNZ 1969: 10⁹ CFU/일, 유산균발효마늘추출물: 1.8 g/일, "
            "Lactiplantibacillus plantarum C29: 800 mg/일); "
            "[한국 MFDS 인정 기능성원료 등록] N=11건 (health_food_ingredient DB)"
        ),  # [NIH-ODS-no-fact-sheet] [MFDS-health_food_ingredient]
        "study_dose": (
            "갑상선 질환 대상 직접 연구 용량 데이터 없음 — "
            "일반 프로바이오틱스 연구에서 1억~1000억 CFU/일 사용; 균주별 적정 용량 다양"
        ),
        "official_upper_limit": (
            "공식 UL 설정 없음 (EFSA·NIH ODS 모두 UL 미설정); "
            "면역억제 환자에서 생균 감염 위험 고려 필요"
        ),
        "counseling_points": [
            "위장관 증상(변비·복부팽만 등) 완화 보조 목적으로 접근 — 갑상선 기능 개선 목적의 직접 근거는 제한적",
            "[LT4 복용] 레보티록신 흡수를 저해한다는 직접 근거는 제한적이나, 복약 패턴 변경 시 공복 복용 유지 확인",
            "균주·CFU는 제품별로 다양 — 표시된 균주/함량 확인 권장",
            "면역저하·중증질환·중심정맥관 보유 시 생균제 감염 위험 고려, 사용 전 상담",
        ],
        "monitoring_parameters": [
            "TSH, Free T4 — 기존 추적 일정에 따라, 또는 제품/복약 패턴 변경 후 6~8주",
            "위장관 증상 (변비·복부팽만·설사 등)",
            "면역저하자·중증질환·중심정맥관 보유자: 발열·균혈증 의심 증상",
        ],
    },

    "vitamin_b12": {
        "applicable_conditions": [
            "hypothyroidism",
            "hashimoto",
            "autoimmune_thyroiditis",
            "b12_deficiency",
        ],
        "possible_benefits": [
            "갑상선기능저하증 환자에서 B12 결핍 동반이 흔함 (자가면역 위장관 손상)",
            "피로, 신경 증상 개선에 기여 가능",
        ],
        "avoid_conditions": [],
        "contraindications": ["cobalt_hypersensitivity"],
        "required_patient_info": ["diagnosis", "lab_values.B12"],
        "evidence_level": "observational",
        "risk_tags": [],
        "notes": "갑상선기능저하증 환자에서 악성빈혈(pernicious anemia) 동반 가능. B12 수치 확인 후 보충 결정 권고.",
        "recommended_dose": "2.4µg/일 (RDA); 결핍 시 500~1000µg/일 (수치에 따라 주1회 주사 가능)",
    },

    "omega3": {
        "applicable_conditions": [
            "hashimoto",
            "autoimmune_thyroiditis",
            "hypothyroidism",
            "graves_disease",
        ],
        "possible_benefits": [
            "항염증 효과 — 자가면역 갑상선 질환에서 염증 조절 가능성",
            "심혈관 보호 효과 (갑상선기능저하증 동반 이상지질혈증)",
        ],
        "avoid_conditions": [],
        "contraindications": ["fish_allergy", "bleeding_disorder_severe"],
        "required_patient_info": ["diagnosis", "medications"],
        "evidence_level": "mechanistic",
        "risk_tags": ["anticoagulant_interaction"],
        "notes": (
            "항응고제(와파린 등) 복용 중 고용량(>3g/일) 오메가3는 출혈 위험 증가 가능. "
            "갑상선 질환 직접 근거는 제한적이며 기전 연구 수준."
        ),
        "recommended_dose": "1~3g/일 (EPA+DHA 합산 기준); 항응고제 복용 시 3g/일 미만",
        "study_dose": (
            "갑상선 질환 특이적 연구 용량 근거 제한적 — "
            "심혈관/자가면역 관련 일반 연구에서 EPA+DHA 1~4g/일 범위 사용"
        ),
        "official_upper_limit": (
            "공식 UL 없음 (FDA 기준 3g/일 초과 시 주의 권고); "
            "항응고 효과 threshold는 3g/일 초과로 알려짐"
        ),
        "counseling_points": [
            "[LT4 복용] 레보티록신과 흡수 상호작용 없음 — 시간 간격 불필요",
            "EPA+DHA 합산 1~3g/일 범위 권고; 3g/일 초과 시 항응고 효과 주의",
            "항응고제(와파린, 아스피린 고용량) 병용 시 출혈 위험 — 처방의 상담 필요",
            "생선 알레르기 환자: 식물성(algae 기반) DHA 고려",
            "개봉 후 냉장 보관 (산패 방지)",
        ],
        "monitoring_parameters": [
            # 항응고제 병용 시 출혈 모니터링 (PT/INR 은 임상 판단)
            "항응고제 병용 시 출혈 증상 또는 PT/INR 모니터링",
            "TSH, Free T4 — 갑상선 기능 추적 (오메가3 직접 영향은 제한적)",
        ],
    },

    # ── Calcium ──────────────────────────────────────────
    "calcium": {
        "applicable_conditions": [
            "hypothyroidism",
            "thyroid_cancer",          # [ATA2015, PMID:26462967] TSH 억제 골건강 — 수술전후 포함
            "thyroid_cancer_postop",
            "thyroidectomy_postop",
            "osteoporosis",
        ],
        "possible_benefits": [
            "[LT4 복용] 골다공증 예방 (레보티록신 장기 복용 환자)",
            "[갑상선 절제술 후] 칼슘 대사 보조",
        ],
        "avoid_conditions": [
            "hypercalcemia",
            "hypercalciuria",
            "kidney_stones",
        ],
        "contraindications": [
            "severe_hypercalcemia",
            "sarcoidosis",
        ],
        "required_patient_info": ["diagnosis", "lab_values.calcium", "medications"],
        "evidence_level": "clinical",
        "risk_tags": ["levothyroxine_timing", "hypercalcemia_risk"],
        "notes": (
            "[LT4 복용] 흡수 상호작용 기전: 칼슘 제제는 위장관 내에서 레보티록신과 결합 또는 흡착되어 "
            "흡수 가능한 자유 레보티록신을 감소시킬 수 있으며, 영향 정도는 개인차·제형에 따라 다름. "
            "[LT4 복용] 탄산칼슘은 LT4 흡수를 약 20% 감소(흡수 84→58%)시키며, 구연산칼슘·초산칼슘 등 "
            "여러 제형에서도 유사한 흡수 감소가 보고되었고(75~81%), 산호칼슘은 탄산칼슘 근거를 외삽해 판단함. "
            "[LT4 복용] 레보티록신과 시간 간격을 두어 복용 권장하되, 4시간 분리는 전통적 관행으로 대조시험 미검증 "
            "(ATA 2014 Q3b, Weak/weak). "
            "원소 칼슘(elemental calcium) 기준 일일 2500mg 초과 시 신장결석·심혈관질환 위험 (식이 섭취 포함 총량 기준). "
            "비타민 D 병용 시 칼슘 흡수 증가 가능. "
            "[갑상선암 수술 후 + 임신] TSH 억제 요법 유지 가능 — 골밀도 모니터링 중요 "
            "(ATA 2017 R66, R73, Weak, low). [갑상선암 TSH 억제 + 폐경 전후 골소실 위험] "
            "칼슘·비타민D 보조 ± 골강화제 고려 (ATA 2015 DTC, Weak). "
            "기존 safety rule `tsh_suppressed_bone_risk` 와 시너지."
        ),  # [ATA2014-Q3b, PMID:25266247] [ATA2017-R66, ATA2017-R73, PMID:28056690] [ATA2015, PMID:26462967]
        "recommended_dose": "1000~1200mg/일; [LT4 복용] 레보티록신과 4시간 간격 권장 (전통적 관행, ATA 2014 Q3b)",
        "study_dose": (
            "Schneyer 2000 (PMID 10838651): calcium carbonate 1200mg/일; "
            "Singh 2011 (PMID 21595516): carbonate/citrate/acetate 비교 — 정확한 용량 논문 확인 권장"
        ),
        "official_upper_limit": (
            "NIH ODS 원소 칼슘 기준 UL: 2500mg/일 (19~50세), 2000mg/일 (51세 이상); "
            "식이 + 보충제 합산 기준"
        ),
        # counseling/monitoring: ATA 2014 Q3b (흡수 간섭 정량·간격) 로 해소 (2026-05-30 9차)
        "counseling_points": [
            "[LT4 복용] 레보티록신(씬지로이드)은 아침 공복에 단독 복용",
            "[LT4 복용] 산호칼슘은 레보티록신 복용 후 최소 4시간 이상 간격 유지",
            "제품 라벨에서 원소 칼슘(elemental calcium) 함량 확인 — 탄산칼슘 기준 약 40%",
            "총 칼슘 섭취량은 식이 + 보충제 합산 2500mg 이하 유지",
            "변비·신장결석 병력 있으면 복용량 감량 또는 제형 변경 고려",
            "고칼슘혈증 증상(구역, 무기력, 혼동) 발생 시 즉시 복용 중단 후 확인",
        ],
        "monitoring_parameters": [
            "TSH, Free T4 — 칼슘 보충 시작·용량 변경 4~8주 후",
            "혈청 Ca, P, Mg",
            "PTH (부갑상선호르몬)",
            "25-OH 비타민D",
            "신기능 (creatinine, eGFR)",
            "골밀도 (DXA) — 연 1회",
        ],
    },

    "ashwagandha": {
        "applicable_conditions": [
            "hypothyroidism",
            "subclinical_hypothyroidism",
        ],
        "possible_benefits": [
            "일부 소규모 RCT에서 갑상선기능저하증 환자의 T3/T4 수치 개선 보고",
            "스트레스 호르몬(코르티솔) 감소 → 갑상선 기능 간접 지원 가능성",
        ],
        "avoid_conditions": [
            "hyperthyroidism",
            "graves_disease",
            "active_hyperthyroidism",
            "autonomous_thyroid_nodule",
        ],
        "contraindications": [
            "pregnancy",
            "autoimmune_disease_on_immunosuppressant",
        ],
        "required_patient_info": ["diagnosis", "medications", "lab_values.TSH"],
        "evidence_level": "mechanistic",
        "risk_tags": ["herb_thyrotoxicosis", "pregnancy_contraindicated"],
        "notes": (
            "갑상선기능항진증 환자에서는 갑상선 자극 효과로 중독증 악화 위험. "
            "임산부 금기. 근거 수준 낮음(소규모 RCT, 단기 추적)."
        ),
        "recommended_dose": "300~600mg/일 (KSM-66/Sensoril 기준); 갑상선기능항진증 금기",
    },

    "vitamin_c": {
        "applicable_conditions": ["hypothyroidism","hashimoto","autoimmune_thyroiditis","thyroid_cancer_postop"],
        "possible_benefits": ["항산화로 갑상선 산화 스트레스 감소","면역 기능 보조","레보티록신 흡수 개선 가능성(소규모 연구)"],
        "avoid_conditions": [],
        "contraindications": ["oxalate_kidney_stones_history"],
        "required_patient_info": ["diagnosis"],
        "evidence_level": "mechanistic",
        "risk_tags": ["high_dose_caution"],
        "notes": "고용량(2000mg↑/일) 장기 복용 시 신장결석 위험. 갑상선 직접 RCT 근거 부족.",
        "recommended_dose": "100~2000mg/일; 상한 2000mg/일",
    },

    "vitamin_a": {
        "applicable_conditions": ["vitamin_a_deficiency"],
        "possible_benefits": ["갑상선 호르몬 수용체 발현 관여","면역 기능 보조"],
        "avoid_conditions": ["hyperthyroidism","liver_disease"],
        "contraindications": ["pregnancy_high_dose","hypervitaminosis_a"],
        "required_patient_info": ["diagnosis","medications"],
        "evidence_level": "mechanistic",
        "risk_tags": ["teratogenic_high_dose","liver_toxicity"],
        "notes": "고용량(10000IU↑/일) 장기 복용 시 간독성·기형 위험. 베타카로틴 형태는 독성 위험 낮음.",
        "recommended_dose": "700~900µg RAE/일; 상한 3000µg RAE/일",
    },

    "vitamin_e": {
        "applicable_conditions": ["hashimoto","autoimmune_thyroiditis","hypothyroidism"],
        "possible_benefits": ["항산화로 갑상선 산화 스트레스 감소","자가면역 염증 완화 가능성"],
        "avoid_conditions": [],
        "contraindications": ["anticoagulant_high_dose"],
        "required_patient_info": ["diagnosis","medications"],
        "evidence_level": "mechanistic",
        "risk_tags": ["anticoagulant_interaction"],
        "notes": "고용량(400IU↑/일) 시 항응고 효과 증가 → 와파린 병용 주의. 갑상선 직접 RCT 근거 부족.",
        "recommended_dose": "15mg(22.4IU)/일; 상한 1000mg/일",
    },

    "vitamin_b6": {
        "applicable_conditions": ["hypothyroidism","hashimoto"],
        "possible_benefits": ["신경전달물질 합성 보조","갑상선기능저하증 피로·신경 증상 완화 가능"],
        "avoid_conditions": [],
        "contraindications": [],
        "required_patient_info": ["diagnosis"],
        "evidence_level": "mechanistic",
        "risk_tags": ["neuropathy_high_dose"],
        "notes": "고용량(100mg↑/일) 장기 복용 시 말초신경병증 위험. 갑상선 직접 근거 부족.",
        "recommended_dose": "1.3~1.7mg/일; 상한 100mg/일",
    },

    "biotin": {
        "applicable_conditions": ["hypothyroidism","alopecia_thyroid"],
        "possible_benefits": ["탈모·손톱 강화","에너지 대사 보조"],
        "avoid_conditions": [],
        "contraindications": [],
        "required_patient_info": ["diagnosis","lab_values.TSH"],
        "evidence_level": "mechanistic",
        "risk_tags": ["lab_interference", "lab_interference_thyroid"],
        "notes": (
            "⚠️ 고용량 비오틴(5mg↑/일)은 스트렙타비딘-비오틴 면역분석 방식 TSH·fT4·T3 검사에서 "
            "위음성(갑상선기능항진처럼 보임) 또는 위양성(갑상선기능저하처럼 보임) 유발 가능. "
            "검사 48~72시간 전 복용 중단 권고. "
            "근거: FDA Safety Communication (2017); Trambas et al. Clin Biochem 2018 (PMID: 29288636)."
        ),
        "recommended_dose": "30µg/일; 탈모 보충 2.5~5mg/일 (검사 간섭 주의)",
    },

    "coq10": {
        "applicable_conditions": ["hypothyroidism","hashimoto","fatigue_thyroid"],
        "possible_benefits": ["미토콘드리아 에너지 생성 보조","갑상선기능저하증 피로 완화 가능","항산화 효과"],
        "avoid_conditions": [],
        "contraindications": [],
        "required_patient_info": ["diagnosis","medications"],
        "evidence_level": "mechanistic",
        "risk_tags": ["anticoagulant_interaction"],
        "notes": "와파린 복용 환자에서 항응고 효과 감소 가능. 갑상선 직접 RCT 근거 부족.",
        "recommended_dose": "100~300mg/일",
    },

    "copper": {
        "applicable_conditions": ["copper_deficiency","hypothyroidism"],
        "possible_benefits": ["갑상선 과산화효소(TPO) 활성 관여","아연 장기 복용 시 구리 결핍 예방"],
        "avoid_conditions": ["wilson_disease","copper_overload"],
        "contraindications": ["wilson_disease"],
        "required_patient_info": ["diagnosis","medications"],
        "evidence_level": "mechanistic",
        "risk_tags": ["wilson_disease_risk"],
        "notes": "아연 고용량 장기 복용 시 구리 결핍 발생 가능 — 아연:구리 8~15:1 비율 권고. 윌슨병 금기.",
        "recommended_dose": "0.9mg/일; 상한 10mg/일",
    },

    "chromium": {
        "applicable_conditions": ["hypothyroidism","insulin_resistance","metabolic_syndrome"],
        "possible_benefits": ["인슐린 감수성 개선","혈당 조절"],
        "avoid_conditions": [],
        "contraindications": [],
        "required_patient_info": ["diagnosis","medications"],
        "evidence_level": "mechanistic",
        "risk_tags": ["drug_interaction","levothyroxine_timing"],
        "notes": "레보티록신 흡수 감소 가능 — 간격 복용 권고. 당뇨약 병용 시 저혈당 주의.",
        "recommended_dose": "25~35µg/일; 보충 200~1000µg/일",
    },

    "arginine": {
        "applicable_conditions": ["hypothyroidism","fatigue_thyroid"],
        "possible_benefits": ["혈관 확장(NO 생성)으로 혈류 개선","면역 기능 보조"],
        "avoid_conditions": ["herpes_simplex_active","recent_myocardial_infarction"],
        "contraindications": ["recent_heart_attack"],
        "required_patient_info": ["diagnosis","medications"],
        "evidence_level": "insufficient",
        "risk_tags": ["insufficient_evidence"],
        "notes": "갑상선 직접 근거 없음. 심근경색 직후 금기(사망률 증가 보고). 헤르페스 활성화 가능성.",
        "recommended_dose": "3~6g/일; 심근경색 병력 시 금기",
    },

    "collagen": {
        "applicable_conditions": ["hypothyroidism","thyroid_cancer_postop"],
        "possible_benefits": ["피부·관절·뼈 건강 보조","갑상선기능저하증 동반 피부 건조 완화 가능성"],
        "avoid_conditions": [],
        "contraindications": ["fish_allergy_marine_collagen"],
        "required_patient_info": ["diagnosis"],
        "evidence_level": "insufficient",
        "risk_tags": [],
        "notes": "갑상선 직접 근거 없음. 어류 콜라겐은 어류 알레르기 환자 주의.",
        "recommended_dose": "5~15g/일 (펩타이드 형태 권장)",
    },

    "lutein": {
        "applicable_conditions": ["graves_orbitopathy","thyroid_eye_disease"],
        "possible_benefits": ["눈 황반 보호 항산화 효과","그레이브스 안병증 동반 시 눈 건강 보조"],
        "avoid_conditions": [],
        "contraindications": [],
        "required_patient_info": ["diagnosis"],
        "evidence_level": "mechanistic",
        "risk_tags": [],
        "notes": "갑상선 직접 근거 없음. 그레이브스 안병증 동반 시 눈 건강 보조 가능.",
        "recommended_dose": "10~20mg/일",
    },

    "milk_thistle": {
        "applicable_conditions": ["hypothyroidism","hashimoto","liver_stress"],
        "possible_benefits": ["간 보호 효과","항산화·항염증 효과"],
        "avoid_conditions": [],
        "contraindications": ["ragweed_allergy"],
        "required_patient_info": ["diagnosis","medications"],
        "evidence_level": "mechanistic",
        "risk_tags": ["herb_drug_interaction"],
        "notes": "CYP450 효소 억제 가능 — 레보티록신 대사 변화 가능성. 국화과 알레르기 환자 주의.",
        "recommended_dose": "140~800mg/일 (실리마린 기준)",
    },

    "glucosamine": {
        "applicable_conditions": ["hypothyroidism","joint_pain_thyroid"],
        "possible_benefits": ["관절 연골 보호","갑상선기능저하증 동반 관절통 완화 가능성"],
        "avoid_conditions": [],
        "contraindications": ["shellfish_allergy"],
        "required_patient_info": ["diagnosis","medications"],
        "evidence_level": "rct",
        "risk_tags": ["anticoagulant_interaction","blood_glucose"],
        "notes": "와파린 병용 시 INR 증가 가능. 당뇨 환자 혈당 모니터링 권고. 갑상선 직접 근거 없음.",
        "recommended_dose": "1500mg/일",
    },

    "chondroitin": {
        "applicable_conditions": ["hypothyroidism","joint_pain_thyroid"],
        "possible_benefits": ["관절 연골 보호","갑상선 질환 동반 관절통 완화 가능성"],
        "avoid_conditions": [],
        "contraindications": [],
        "required_patient_info": ["diagnosis","medications"],
        "evidence_level": "rct",
        "risk_tags": ["anticoagulant_interaction"],
        "notes": "항응고제(와파린 등) 병용 시 출혈 위험 증가 가능성. 갑상선 호르몬제와 직접적 상호작용 근거 없음.",
        "recommended_dose": "800~1200mg/일",
    },

    "propolis": {
        "applicable_conditions": ["hashimoto", "hyperthyroidism"],
        "possible_benefits": ["항산화 작용", "항균 및 면역 지원"],
        "avoid_conditions": ["autoimmune_disease_on_immunosuppressant"],
        "contraindications": ["pollen_allergy", "bee_allergy"],
        "required_patient_info": ["diagnosis", "medications"],
        "evidence_level": "mechanistic",
        "risk_tags": ["immune_stimulation"],
        "notes": "면역 자극(면역 조절) 작용이 있어 하시모토나 그레이브스병 같은 자가면역 갑상선 질환의 경우 이론적으로 주의가 필요함. 벌이나 꽃가루 알레르기 주의.",
        "recommended_dose": "17mg/일 (플라보노이드 기준)",
    },

    "melatonin": {
        "applicable_conditions": ["hypothyroidism","sleep_disorder_thyroid","hashimoto"],
        "possible_benefits": ["수면 장애 개선","항산화·면역 조절 가능성"],
        "avoid_conditions": ["hyperthyroidism","autoimmune_disease_on_immunosuppressant"],
        "contraindications": [],
        "required_patient_info": ["diagnosis","medications"],
        "evidence_level": "rct",
        "risk_tags": ["anticoagulant_interaction","sedation"],
        "notes": "갑상선기능항진증에서 멜라토닌 수치 변화로 주의. 항응고제 병용 시 출혈 위험 증가 가능.",
        "recommended_dose": "0.5~5mg/일 (취침 30분 전); 저용량부터 시작",
    },

    "nac": {
        "applicable_conditions": ["hashimoto","autoimmune_thyroiditis","hypothyroidism"],
        "possible_benefits": ["글루타치온 전구체 — 갑상선 항산화 방어 보조","자가면역 염증 완화 가능성"],
        "avoid_conditions": [],
        "contraindications": ["asthma_severe"],
        "required_patient_info": ["diagnosis"],
        "evidence_level": "mechanistic",
        "risk_tags": [],
        "notes": "갑상선 직접 RCT 근거 없음. 천식 환자에서 기관지 수축 유발 가능.",
        "recommended_dose": "600~1800mg/일",
    },

    "spirulina": {
        "applicable_conditions": [],
        "possible_benefits": ["단백질·미량원소 공급","항산화 효과"],
        "avoid_conditions": ["hyperthyroidism","graves_disease","hashimoto","autoimmune_thyroiditis"],
        "contraindications": ["phenylketonuria","autoimmune_disease_active"],
        "required_patient_info": ["diagnosis"],
        "evidence_level": "mechanistic",
        "risk_tags": ["iodine_excess","autoimmune_stimulation"],
        "notes": "⚠️ 요오드 함량 높아 갑상선 질환자에서 기능 악화 위험. 하시모토·그레이브스 환자 비권장.",
        "recommended_dose": "1~3g/일; 갑상선 질환 시 전문의 상담 필수",
    },

    "green_tea_extract": {
        "applicable_conditions": ["hypothyroidism","hashimoto"],
        "possible_benefits": ["항산화·항염증 효과","대사 촉진 가능성"],
        "avoid_conditions": ["hyperthyroidism","liver_disease"],
        "contraindications": [],
        "required_patient_info": ["diagnosis","medications"],
        "evidence_level": "mechanistic",
        "risk_tags": ["liver_toxicity_high_dose","levothyroxine_timing"],
        "notes": "고용량(800mg↑/일) 장기 복용 시 간독성 보고. 레보티록신 흡수 감소 가능 — 간격 복용 권고.",
        "recommended_dose": "250~500mg/일 (EGCG 기준); 상한 800mg/일",
    },

    "berberine": {
        "applicable_conditions": ["hypothyroidism","insulin_resistance","metabolic_syndrome"],
        "possible_benefits": ["혈당·지질 개선","대사 증후군 보조"],
        "avoid_conditions": ["hyperthyroidism"],
        "contraindications": ["pregnancy","neonatal_jaundice_risk"],
        "required_patient_info": ["diagnosis","medications"],
        "evidence_level": "rct",
        "risk_tags": ["drug_interaction","pregnancy_contraindicated"],
        "notes": "레보티록신 흡수·대사 변화 가능 — 간격 복용 권고. 임산부 금기(황달 위험). 당뇨약 병용 저혈당 주의.",
        "recommended_dose": "500mg × 3회/일 (식전)",
    },

    "alpha_lipoic_acid": {
        "applicable_conditions": ["hypothyroidism","hashimoto","autoimmune_thyroiditis"],
        "possible_benefits": ["강력한 항산화 효과","인슐린 감수성 개선","갑상선 조직 보호 가능성"],
        "avoid_conditions": ["hyperthyroidism"],
        "contraindications": [],
        "required_patient_info": ["diagnosis","medications"],
        "evidence_level": "mechanistic",
        "risk_tags": ["levothyroxine_timing","blood_glucose"],
        "notes": "레보티록신 흡수 감소 가능 — 간격 복용 권고. 당뇨약 병용 시 저혈당 주의.",
        "recommended_dose": "300~600mg/일",
    },

    "lecithin": {
        "applicable_conditions": ["hypothyroidism","hashimoto"],
        "possible_benefits": ["지질 대사 보조","간 건강 보조"],
        "avoid_conditions": [],
        "contraindications": ["soy_allergy_soy_lecithin","egg_allergy_egg_lecithin"],
        "required_patient_info": ["diagnosis"],
        "evidence_level": "insufficient",
        "risk_tags": [],
        "notes": "갑상선 직접 근거 없음. 콩 레시틴 — 콩 알레르기 주의. 달걀 레시틴 — 달걀 알레르기 주의.",
        "recommended_dose": "1200~2400mg/일",
    },

    "quercetin": {
        "applicable_conditions": ["hashimoto","autoimmune_thyroiditis"],
        "possible_benefits": ["항산화·항염증 효과","자가면역 염증 완화 가능성"],
        "avoid_conditions": ["hyperthyroidism"],
        "contraindications": [],
        "required_patient_info": ["diagnosis","medications"],
        "evidence_level": "mechanistic",
        "risk_tags": ["cyp3a4_interaction","tpo_inhibition_in_vitro"],
        "notes": (
            "in vitro 연구에서 TPO(갑상선 과산화효소) 활성 억제 가능성 보고 — 고용량 장기 복용 시 주의. "
            "CYP3A4 효소 억제 → 스타틴·면역억제제·일부 항응고제와 상호작용 가능."
        ),
        "recommended_dose": "500~1000mg/일",
    },

    "resveratrol": {
        "applicable_conditions": ["hashimoto","autoimmune_thyroiditis","hypothyroidism"],
        "possible_benefits": ["항산화·항염증 효과","심혈관 보호 가능성"],
        "avoid_conditions": ["hyperthyroidism"],
        "contraindications": [],
        "required_patient_info": ["diagnosis","medications"],
        "evidence_level": "mechanistic",
        "risk_tags": ["anticoagulant_interaction","goitrogenic_in_vitro"],
        "notes": (
            "일부 in vitro 연구에서 갑상선 호르몬 합성 억제 가능성. "
            "항응고제(와파린, 아스피린)와 병용 시 출혈 위험 증가 가능."
        ),
        "recommended_dose": "100~500mg/일",
    },

    "curcumin": {
        "applicable_conditions": ["hashimoto","autoimmune_thyroiditis","hypothyroidism"],
        "possible_benefits": ["강력한 항염증·항산화 효과","자가면역 갑상선 염증 완화 가능성(소규모 연구)"],
        "avoid_conditions": [],
        "contraindications": ["gallstones","biliary_obstruction"],
        "required_patient_info": ["diagnosis","medications"],
        "evidence_level": "observational",
        "risk_tags": ["anticoagulant_interaction","cyp3a4_interaction"],
        "notes": (
            "흡수율이 낮아 피페린(후추 추출물) 병용 제제 권장. "
            "항응고제·당뇨약과 병용 시 효과 강화 가능 — 출혈/저혈당 주의. "
            "담낭 결석/담도 폐쇄 환자 금기."
        ),
        "recommended_dose": "500~2000mg/일 (커큐미노이드 기준)",
    },

    "l_theanine": {
        "applicable_conditions": ["hyperthyroidism","graves_disease","sleep_disorder_thyroid"],
        "possible_benefits": ["항스트레스·이완 효과","수면 질 개선","갑상선기능항진증 동반 불안 완화 가능성"],
        "avoid_conditions": [],
        "contraindications": [],
        "required_patient_info": ["diagnosis","medications"],
        "evidence_level": "mechanistic",
        "risk_tags": ["antihypertensive_interaction"],
        "notes": (
            "갑상선 직접 임상 근거는 부족하나, 항진증 환자의 불안/수면 보조에 도움 가능성. "
            "항고혈압제와 병용 시 저혈압 강화 가능성 주의."
        ),
        "recommended_dose": "100~400mg/일",
    },

    "evening_primrose": {
        "applicable_conditions": ["hashimoto","autoimmune_thyroiditis"],
        "possible_benefits": ["감마리놀렌산(GLA) 공급 — 항염증","피부 건조 개선"],
        "avoid_conditions": ["seizure_disorder"],
        "contraindications": [],
        "required_patient_info": ["diagnosis","medications"],
        "evidence_level": "insufficient",
        "risk_tags": ["anticoagulant_interaction","seizure_risk"],
        "notes": (
            "달맞이꽃 종자유 — GLA 함유. 갑상선 직접 근거는 제한적. "
            "항응고제와 병용 시 출혈 위험 증가. 간질 병력 시 발작 역치 저하 가능성."
        ),
        "recommended_dose": "1000~3000mg/일 (GLA 240~720mg)",
    },
}


# ── 한국어 별칭 → canonical key 공유 매핑 ──
_SUPPLEMENT_ALIASES = {
    # 요오드
    "요오드": "iodine", "아이오딘": "iodine", "iodine": "iodine",
    # 셀레늄
    "셀레늄": "selenium", "셀렌": "selenium", "셀레니움": "selenium", "selenium": "selenium",
    # 철분
    "철분": "iron", "철": "iron", "iron": "iron", "페로": "iron",
    "철분제": "iron", "철제": "iron", "iron_supplement": "iron",
    "ferrous": "iron", "ferrous_sulfate": "iron", "ferritin": "iron",
    # 비타민D
    "비타민d": "vitamin_d", "비타민 d": "vitamin_d", "비타민_d": "vitamin_d",
    "vit_d": "vitamin_d", "vitamin d": "vitamin_d",
    "vitamin d3": "vitamin_d", "vitamin_d3": "vitamin_d",
    "cholecalciferol": "vitamin_d", "calciferol": "vitamin_d",
    "ergocalciferol": "vitamin_d", "d3": "vitamin_d",
    "vitamin d3": "vitamin_d", "vitamin_d3": "vitamin_d",
    "cholecalciferol": "vitamin_d", "calciferol": "vitamin_d",
    "ergocalciferol": "vitamin_d", "d3": "vitamin_d",
    # 아연
    "아연": "zinc", "zinc": "zinc",
    # 마그네슘
    "마그네슘": "magnesium", "magnesium": "magnesium",
    # 프로바이오틱스
    "프로바이오틱스": "probiotics", "유산균": "probiotics", "probiotics": "probiotics",
    "락토바실러스": "probiotics", "비피더스": "probiotics",
    # 비타민B12
    "비타민b12": "vitamin_b12", "비타민 b12": "vitamin_b12",
    "b12": "vitamin_b12", "코발라민": "vitamin_b12",
    "methylcobalamin": "vitamin_b12", "cyanocobalamin": "vitamin_b12",
    # 오메가3
    "오메가3": "omega3", "오메가-3": "omega3", "omega3": "omega3",
    "omega_3": "omega3", "omega-3": "omega3",
    "fish oil": "omega3", "fish_oil": "omega3", "피쉬오일": "omega3", "어유": "omega3",
    "dha": "omega3", "epa": "omega3",
    "omega-3 fatty acids": "omega3", "omega 3 fatty acids": "omega3",
    "triple strength fish oil": "omega3",
    # 아슈와간다
    "아슈와간다": "ashwagandha", "위타니아": "ashwagandha",
    "withania somnifera": "ashwagandha", "ashwagandha": "ashwagandha",
    # 칼슘
    "칼슘": "calcium", "산호칼슘": "calcium", "coral calcium": "calcium",
    "calcium carbonate": "calcium", "calcium citrate": "calcium",
    "calcium": "calcium", "ca": "calcium",
    # 비타민C
    "비타민c": "vitamin_c", "비타민 c": "vitamin_c", "vitamin c": "vitamin_c",
    "ascorbic acid": "vitamin_c", "아스코르브산": "vitamin_c",
    # 비타민A
    "비타민a": "vitamin_a", "비타민 a": "vitamin_a", "vitamin a": "vitamin_a",
    "레티놀": "vitamin_a", "retinol": "vitamin_a", "베타카로틴": "vitamin_a",
    # 비타민E
    "비타민e": "vitamin_e", "비타민 e": "vitamin_e", "vitamin e": "vitamin_e",
    "토코페롤": "vitamin_e", "tocopherol": "vitamin_e",
    # 비타민B6
    "비타민b6": "vitamin_b6", "비타민 b6": "vitamin_b6", "b6": "vitamin_b6",
    "피리독신": "vitamin_b6", "pyridoxine": "vitamin_b6",
    # 비오틴
    "비오틴": "biotin", "바이오틴": "biotin", "biotin": "biotin", "비타민b7": "biotin",
    "비타민 b7": "biotin", "비타민h": "biotin",
    # CoQ10
    "코엔자임q10": "coq10", "코큐텐": "coq10", "coq10": "coq10",
    "코엔자임 q10": "coq10", "ubiquinol": "coq10", "유비퀴놀": "coq10",
    # 구리
    "구리": "copper", "copper": "copper",
    # 크롬
    "크롬": "chromium", "chromium": "chromium",
    # 아르기닌
    "아르기닌": "arginine", "arginine": "arginine", "l-arginine": "arginine",
    "엘아르기닌": "arginine",
    # 콜라겐
    "콜라겐": "collagen", "collagen": "collagen", "콜라겐펩타이드": "collagen",
    # 루테인
    "루테인": "lutein", "lutein": "lutein", "루테인지아잔틴": "lutein",
    "지아잔틴": "lutein",
    # 밀크씨슬
    "밀크씨슬": "milk_thistle", "실리마린": "milk_thistle",
    "milk thistle": "milk_thistle", "silymarin": "milk_thistle",
    # 글루코사민
    "글루코사민": "glucosamine", "glucosamine": "glucosamine",
    # 멜라토닌
    "멜라토닌": "melatonin", "melatonin": "melatonin",
    # NAC
    "nac": "nac", "n-아세틸시스테인": "nac",
    "n-acetylcysteine": "nac", "아세틸시스테인": "nac",
    # 스피루리나
    "스피루리나": "spirulina", "spirulina": "spirulina",
    # 녹차추출물
    "녹차추출물": "green_tea_extract", "녹차 추출물": "green_tea_extract",
    "egcg": "green_tea_extract", "green tea extract": "green_tea_extract",
    # 베르베린
    "베르베린": "berberine", "berberine": "berberine",
    # 알파리포산
    "알파리포산": "alpha_lipoic_acid", "ala": "alpha_lipoic_acid",
    "alpha lipoic acid": "alpha_lipoic_acid", "lipoic acid": "alpha_lipoic_acid",
    # 레시틴
    "레시틴": "lecithin", "lecithin": "lecithin", "포스파티딜콜린": "lecithin",
    # 퀘르세틴
    "퀘르세틴": "quercetin", "케르세틴": "quercetin", "quercetin": "quercetin",
    # 레스베라트롤
    "레스베라트롤": "resveratrol", "레스베라톨": "resveratrol", "resveratrol": "resveratrol",
    # 커큐민
    "커큐민": "curcumin", "강황": "curcumin", "울금": "curcumin",
    "curcumin": "curcumin", "turmeric": "curcumin",
    # L-테아닌
    "테아닌": "l_theanine", "l-테아닌": "l_theanine", "엘테아닌": "l_theanine",
    "l-theanine": "l_theanine", "theanine": "l_theanine",
    # 달맞이꽃 종자유
    "달맞이꽃": "evening_primrose", "달맞이꽃종자유": "evening_primrose",
    "달맞이꽃 종자유": "evening_primrose", "감마리놀렌산": "evening_primrose",
    "gla": "evening_primrose", "evening primrose": "evening_primrose",
    "evening primrose oil": "evening_primrose", "epo": "evening_primrose",
}


# ── canonical key → 한국어 표시명 매핑 ──
_CANONICAL_TO_KO = {
    "iodine": "요오드",
    "selenium": "셀레늄",
    "iron": "철분",
    "vitamin_d": "비타민D",
    "multivitamin": "종합비타민/멀티비타민",
    "zinc": "아연",
    "magnesium": "마그네슘",
    "probiotics": "프로바이오틱스",
    "vitamin_b12": "비타민B12",
    "omega3": "오메가3",
    "ashwagandha": "아슈와간다",
    "calcium": "칼슘",
    "vitamin_c": "비타민C",
    "vitamin_a": "비타민A",
    "vitamin_e": "비타민E",
    "vitamin_b6": "비타민B6",
    "biotin": "비오틴",
    "coq10": "코엔자임Q10",
    "copper": "구리",
    "chromium": "크롬",
    "arginine": "아르기닌",
    "collagen": "콜라겐",
    "lutein": "루테인",
    "milk_thistle": "밀크씨슬",
    "glucosamine": "글루코사민",
    "chondroitin": "콘드로이친",
    "melatonin": "멜라토닌",
    "propolis": "프로폴리스",
    "nac": "NAC(N-아세틸시스테인)",
    "spirulina": "스피루리나",
    "green_tea_extract": "녹차추출물(EGCG)",
    "berberine": "베르베린",
    "alpha_lipoic_acid": "알파리포산",
    "lecithin": "레시틴",
    "quercetin": "퀘르세틴",
    "resveratrol": "레스베라트롤",
    "curcumin": "커큐민(강황)",
    "l_theanine": "L-테아닌",
    "evening_primrose": "달맞이꽃 종자유",
}


# ── canonical key → PubMed 표준 검색 쿼리 매핑 ──────────────────────────────
# 각 성분의 보충제 맥락이 명확히 드러나도록 구체화된 쿼리
_PUBMED_QUERY_MAP: Dict[str, str] = {
    "iodine":            "iodine supplement thyroid function",
    "selenium":          "selenium supplementation thyroid autoimmunity",
    "iron":              "iron deficiency thyroid function",
    "vitamin_d":         "vitamin D supplementation thyroid",
    "multivitamin":      "multivitamin supplement iodine thyroid function",
    "zinc":              "zinc supplement thyroid hormone",
    "magnesium":         "magnesium supplement thyroid",
    "probiotics":        "probiotics gut thyroid axis",
    "vitamin_b12":       "vitamin B12 deficiency thyroid",
    "omega3":            "omega-3 fatty acids thyroid autoimmunity",
    "ashwagandha":       "ashwagandha thyroid hormone",
    "calcium":           "calcium supplement thyroid levothyroxine",
    "vitamin_c":         "vitamin C antioxidant thyroid",
    "vitamin_a":         "vitamin A thyroid function",
    "vitamin_e":         "vitamin E thyroid oxidative stress",
    "vitamin_b6":        "vitamin B6 thyroid function",
    "biotin":            "biotin supplement thyroid test interference",
    "coq10":             "coenzyme Q10 thyroid oxidative stress",
    "copper":            "copper thyroid hormone metabolism",
    "chromium":          "chromium supplement thyroid glucose",
    "arginine":          "L-arginine supplement thyroid",
    "collagen":          "collagen supplement thyroid",
    "lutein":            "lutein supplement thyroid",
    "milk_thistle":      "milk thistle silymarin thyroid",
    "glucosamine":       "glucosamine supplement thyroid",
    "chondroitin":       "chondroitin supplement thyroid",
    "melatonin":         "melatonin thyroid hormone",
    "propolis":          "propolis thyroid autoimmune",
    "nac":               "N-acetylcysteine antioxidant thyroid",
    "spirulina":         "spirulina thyroid iodine",
    "green_tea_extract": "EGCG green tea extract thyroid",
    "berberine":         "berberine thyroid hormone metabolism",
    "alpha_lipoic_acid": "alpha lipoic acid thyroid antioxidant",
    "lecithin":          "lecithin phosphatidylcholine thyroid",
    "quercetin":         "quercetin flavonoid thyroid",
    "resveratrol":       "resveratrol thyroid hormone",
    "curcumin":          "curcumin thyroid anti-inflammatory",
    "l_theanine":        "L-theanine thyroid stress",
    "evening_primrose":  "evening primrose oil GLA thyroid",
}


def get_pubmed_query(canonical_key: str) -> Optional[str]:
    """canonical key에 대응하는 PubMed 표준 검색 쿼리 반환. 미등록이면 None."""
    return _PUBMED_QUERY_MAP.get(canonical_key)


def get_display_name(name: str) -> str:
    """canonical key → 한국어 표시명. 미등록이면 입력 그대로 반환."""
    key = name.strip().lower().replace(" ", "_").replace("-", "_")
    return _CANONICAL_TO_KO.get(key, name)


def _strip_korean_supplement_suffix(key: str) -> str:
    """한국어 영양제 이름에서 흔한 접미사를 제거.

    "철분제" → "철분", "칼슘제" → "칼슘", "비타민d 보충제" → "비타민d".
    별칭 사전에 누락된 변형이 있어도 정규화가 한 번 더 시도되도록 안전망 역할.
    """
    if not key:
        return key
    for suffix in ("보충제", "영양제", "제제", "제"):
        if key.endswith(suffix) and len(key) > len(suffix):
            stripped = key[: -len(suffix)].rstrip("_ ")
            if stripped:
                return stripped
    return key


def _resolve_supplement_key(name: str) -> str:
    """입력 이름을 canonical key로 정규화. 별칭 누락 케이스에 접미사 제거 fallback 적용."""
    key = name.strip().lower().replace(" ", "_").replace("-", "_")
    if key in _SUPPLEMENT_ALIASES:
        return _SUPPLEMENT_ALIASES[key]
    if key in SUPPLEMENT_RULES:
        return key
    stripped = _strip_korean_supplement_suffix(key)
    if stripped != key:
        if stripped in _SUPPLEMENT_ALIASES:
            return _SUPPLEMENT_ALIASES[stripped]
        if stripped in SUPPLEMENT_RULES:
            return stripped
    return key


def get_supplement_rule(name: str) -> Optional[Dict[str, Any]]:
    """정규화된 이름으로 rule 조회. 없으면 None."""
    return SUPPLEMENT_RULES.get(_resolve_supplement_key(name))


def list_supplement_rules() -> List[str]:
    """등록된 모든 supplement rule 이름 목록."""
    return list(SUPPLEMENT_RULES.keys())


# ─────────────────────────────────────────────────────────────
# 검증 상태 레지스트리 (AGENT_SPEC §3.7 / §5)
#   VERIFIED_SUPPLEMENTS: 공신력 출처(가이드라인/NIH ODS/KDRI/MFDS) 부착·검증 완료.
#   그 외(롱테일)는 **데모용 미검증** — LLM 초안, 교수님 임상 검증 전. 동작은 동일(데모 유지),
#   표시·관리·향후 disclaimer 용 단일 진실원.
#   ※ 검증군 내 일부 study_dose(magnesium/vitamin_d/zinc)는 "근거 제한적"으로 표기된
#     근거 보강 대상 — review_queue.md 추적.
# ─────────────────────────────────────────────────────────────
VERIFIED_SUPPLEMENTS = frozenset({
    "iodine", "selenium", "iron", "vitamin_d", "zinc", "magnesium",
    "probiotics",
})


def is_verified_supplement(name: str) -> bool:
    """공신력 출처 검증 완료 영양제 여부. False = 데모용 미검증(LLM 초안)."""
    return _resolve_supplement_key(name) in VERIFIED_SUPPLEMENTS


def list_unverified_supplements() -> List[str]:
    """데모용 미검증(롱테일) 영양제 목록."""
    return [k for k in SUPPLEMENT_RULES if k not in VERIFIED_SUPPLEMENTS]


def get_supplement_key(name: str) -> Optional[str]:
    """입력 이름을 canonical rule key로 변환. 미등록이면 None."""
    key = _resolve_supplement_key(name)
    return key if key in SUPPLEMENT_RULES else None


def normalize_supplement_name(token: str) -> Optional[str]:
    """
    단일 토큰을 canonical supplement key로 변환 (정확 매핑 전용).
    _SUPPLEMENT_ALIASES 또는 SUPPLEMENT_RULES에 없으면 None 반환.
    db.py의 DB fallback 토큰별 매핑에 사용 — 퍼지 매칭 없음.
    """
    t = token.strip().lower().replace(" ", "_").replace("-", "_")
    if t in _SUPPLEMENT_ALIASES:
        candidate = _SUPPLEMENT_ALIASES[t]
        if candidate in SUPPLEMENT_RULES:
            return candidate
    if t in SUPPLEMENT_RULES:
        return t
    return None


def _fuzzy_match_supplement(term: str, cutoff: float = 0.85) -> Optional[str]:
    """별칭 목록과 퍼지 매칭. 유사도 cutoff 이상이면 canonical key 반환, 아니면 None."""
    from difflib import get_close_matches
    all_aliases = list(_SUPPLEMENT_ALIASES.keys()) + list(SUPPLEMENT_RULES.keys())
    matches = get_close_matches(term, all_aliases, n=1, cutoff=cutoff)
    if matches:
        matched = matches[0]
        return _SUPPLEMENT_ALIASES.get(matched, matched)
    return None


def normalize_supplement_name_fuzzy(name: str) -> str:
    """영양제 이름을 canonical key로 변환. 정확 매칭 실패 시 퍼지 매칭 시도. 미등록이면 원본 소문자 반환."""
    key = name.strip().lower().replace(" ", "_").replace("-", "_")
    if key in _SUPPLEMENT_ALIASES:
        return _SUPPLEMENT_ALIASES[key]
    if key in SUPPLEMENT_RULES:
        return key
    return _fuzzy_match_supplement(key) or key


def infer_supplement_from_message(message: str) -> tuple[Optional[str], Optional[str]]:
    """
    자유 입력 메시지에서 알려진 영양제 키워드를 추출하여 (canonical_key, original_term) 반환.
    여러 개 매칭 시 메시지에서 가장 먼저 나오는 것을 반환.
    매칭 없으면 (None, None).
    """
    text = (message or "").strip().lower()
    if not text:
        return None, None

    # 긴 키워드 우선 매칭 (예: "비타민 d"가 "비타민"보다 먼저)
    _KEYWORD_MAP = {
        # 요오드
        "요오드": "iodine", "아이오딘": "iodine", "iodine": "iodine",
        # 셀레늄
        "셀레늄": "selenium", "셀렌": "selenium", "셀레니움": "selenium", "selenium": "selenium",
        # 철분
        "철분": "iron", "페로": "iron", "iron": "iron",
        # 비타민D (긴 것 먼저)
        "비타민 d": "vitamin_d", "비타민d": "vitamin_d", "vitamin d": "vitamin_d",
        # 비타민C
        "비타민 c": "vitamin_c", "비타민c": "vitamin_c", "vitamin c": "vitamin_c",
        "아스코르브산": "vitamin_c", "ascorbic acid": "vitamin_c",
        # 비타민A
        "비타민 a": "vitamin_a", "비타민a": "vitamin_a", "vitamin a": "vitamin_a",
        "레티놀": "vitamin_a", "베타카로틴": "vitamin_a",
        # 비타민E
        "비타민 e": "vitamin_e", "비타민e": "vitamin_e", "vitamin e": "vitamin_e",
        "토코페롤": "vitamin_e",
        # 비타민B12 (b12보다 긴 것 먼저)
        "비타민 b12": "vitamin_b12", "비타민b12": "vitamin_b12", "코발라민": "vitamin_b12",
        "methylcobalamin": "vitamin_b12", "b12": "vitamin_b12",
        # 비타민B6 (b6보다 긴 것 먼저)
        "비타민 b6": "vitamin_b6", "비타민b6": "vitamin_b6", "피리독신": "vitamin_b6", "b6": "vitamin_b6",
        # 비오틴
        "비타민 b7": "biotin", "비타민b7": "biotin", "비오틴": "biotin", "biotin": "biotin",
        # CoQ10
        "코엔자임 q10": "coq10", "코엔자임q10": "coq10", "코큐텐": "coq10",
        "coq10": "coq10", "ubiquinol": "coq10", "유비퀴놀": "coq10",
        # 아연
        "아연": "zinc", "zinc": "zinc",
        # 마그네슘
        "마그네슘": "magnesium", "magnesium": "magnesium",
        # 프로바이오틱스
        "프로바이오틱스": "probiotics", "유산균": "probiotics", "락토바실러스": "probiotics",
        "비피더스": "probiotics", "probiotics": "probiotics",
        # 오메가3
        "오메가-3": "omega3", "오메가3": "omega3", "fish oil": "omega3",
        "피쉬오일": "omega3", "어유": "omega3", "dha": "omega3", "epa": "omega3",
        # 칼슘
        "칼슘": "calcium", "산호칼슘": "calcium", "coral calcium": "calcium",
        "calcium carbonate": "calcium", "calcium citrate": "calcium",
        "calcium": "calcium",
        # 종합비타민
        "종합비타민": "multivitamin", "멀티비타민": "multivitamin",
        "종합 비타민": "multivitamin", "멀티 비타민": "multivitamin",
        "multivitamin": "multivitamin", "multi vitamin": "multivitamin",
        # 아슈와간다
        "아슈와간다": "ashwagandha", "위타니아": "ashwagandha", "ashwagandha": "ashwagandha",
        # 구리
        "구리": "copper", "copper": "copper",
        # 크롬
        "크롬": "chromium", "chromium": "chromium",
        # 아르기닌
        "l-arginine": "arginine", "엘아르기닌": "arginine",
        "아르기닌": "arginine", "arginine": "arginine",
        # 콜라겐
        "콜라겐펩타이드": "collagen", "콜라겐": "collagen", "collagen": "collagen",
        # 루테인
        "루테인지아잔틴": "lutein", "루테인": "lutein", "지아잔틴": "lutein", "lutein": "lutein",
        # 밀크씨슬
        "milk thistle": "milk_thistle", "밀크씨슬": "milk_thistle",
        "실리마린": "milk_thistle", "silymarin": "milk_thistle",
        # 글루코사민
        "글루코사민": "glucosamine", "glucosamine": "glucosamine",
        # 콘드로이친
        "콘드로이친": "chondroitin", "뮤코다당단백": "chondroitin", "chondroitin": "chondroitin",
        # 멜라토닌
        "멜라토닌": "melatonin", "melatonin": "melatonin",
        # 프로폴리스
        "프로폴리스": "propolis", "propolis": "propolis",
        # NAC
        "n-acetylcysteine": "nac", "n-아세틸시스테인": "nac",
        "아세틸시스테인": "nac", "nac": "nac",
        # 스피루리나
        "스피루리나": "spirulina", "spirulina": "spirulina",
        # 녹차추출물
        "녹차 추출물": "green_tea_extract", "녹차추출물": "green_tea_extract",
        "green tea extract": "green_tea_extract", "egcg": "green_tea_extract",
        # 베르베린
        "베르베린": "berberine", "berberine": "berberine",
        # 알파리포산
        "alpha lipoic acid": "alpha_lipoic_acid", "알파리포산": "alpha_lipoic_acid",
        "lipoic acid": "alpha_lipoic_acid",
        # 퀘르세틴
        "퀘르세틴": "quercetin", "케르세틴": "quercetin", "quercetin": "quercetin",
        # 레스베라트롤
        "레스베라트롤": "resveratrol", "레스베라톨": "resveratrol", "resveratrol": "resveratrol",
        # 커큐민
        "커큐민": "curcumin", "강황": "curcumin", "울금": "curcumin",
        "curcumin": "curcumin", "turmeric": "curcumin",
        # L-테아닌
        "l-테아닌": "l_theanine", "테아닌": "l_theanine", "엘테아닌": "l_theanine",
        "l-theanine": "l_theanine", "theanine": "l_theanine",
        # 달맞이꽃 종자유
        "달맞이꽃 종자유": "evening_primrose", "달맞이꽃종자유": "evening_primrose",
        "달맞이꽃": "evening_primrose", "감마리놀렌산": "evening_primrose",
        "evening primrose oil": "evening_primrose", "evening primrose": "evening_primrose",
        # 레시틴
        "포스파티딜콜린": "lecithin", "레시틴": "lecithin", "lecithin": "lecithin",
    }

    # 키워드를 길이 역순 정렬 (긴 것 우선 매칭)
    sorted_keywords = sorted(_KEYWORD_MAP.keys(), key=len, reverse=True)

    best_pos = len(text) + 1
    best_key: Optional[str] = None
    for keyword in sorted_keywords:
        pos = text.find(keyword)
        if pos != -1 and pos < best_pos:
            best_pos = pos
            best_key = _KEYWORD_MAP[keyword]

    if best_key:
        return best_key, None

    # LLM fallback: 키워드 매칭 실패 시 LLM으로 canonical key 직접 선택
    return _infer_canonical_key_with_llm(message)


def _infer_canonical_key_with_llm(message: str) -> tuple[Optional[str], Optional[str]]:
    """
    SUPPLEMENT_RULES의 canonical key 목록을 LLM에 제공하고,
    메시지에서 가장 적합한 key 1개와 사용자가 입력한 원래 영양제/브랜드명을 반환한다.
    해당 없으면 (None, None) 반환.

    내부적으로 _infer_ingredients_with_llm() 를 호출하고 첫 번째 결과를 반환한다.
    (infer_supplement_from_message 하위 호환 유지용 wrapper)
    """
    results = _infer_ingredients_with_llm(message)
    if results:
        key, original_term = results[0]
        return key, original_term
    return None, None


def _infer_ingredients_with_llm(message: str) -> List[tuple[str, Optional[str]]]:
    """
    SUPPLEMENT_RULES의 canonical key 목록을 LLM에 제공하고,
    메시지에서 언급된 **모든 성분**을 (canonical_key, confidence) 리스트로 반환한다.
    복합제·복수 성분 입력을 지원한다.
    해당 없으면 빈 리스트 반환.

    반환 타입: List[tuple[canonical_key, original_term]]
    """
    try:
        import json as _json
        from domain.consultation.pubmed.openai_client import _get_openai_client
        registered = list(SUPPLEMENT_RULES.keys())
        client = _get_openai_client()
        prompt = (
            f"당신은 영양제·건강기능식품 성분 분류 전문가입니다.\n"
            f"아래 사용자 문장에서 언급된 영양제·건강기능식품의 주성분을 파악하고,"
            f" 등록된 canonical key 목록에서 매핑하세요.\n\n"
            f"[사용자 문장]\n{message}\n\n"
            f"[등록된 canonical key 목록]\n{', '.join(registered)}\n\n"
            f"규칙:\n"
            f"1. JSON 형식으로 반환:\n"
            f"   {{\"product_label\": \"사용자가 말한 제품/브랜드명\","
            f" \"ingredients\": [{{\"key\": \"canonical_key\", \"confidence\": 0.0~1.0}}]}}\n"
            f"2. ingredients 에는 화학적/생리활성학적으로 정확히 부합하는 성분만 담으세요."
            f" 억지 매핑 절대 금지 (예: 콘드로이친 → glucosamine X).\n"
            f"3. 성분이 없거나 목록에 없으면: {{\"product_label\": \"none\", \"ingredients\": []}}\n"
            f"4. 브랜드명만 단독 언급(예: '고려은단', '종근당')이면:"
            f" {{\"product_label\": \"브랜드명\", \"ingredients\": []}}\n"
            f"5. confidence: 1.0=확실, 0.8=높음, 0.6=중간, 0.4=낮음.\n"
            f"6. 설명 금지."
        )
        response = client.chat.completions.create(
            model="gpt-4o-mini",
            messages=[{"role": "user", "content": prompt}],
            response_format={"type": "json_object"},
            temperature=0,
        )
        raw = _json.loads(response.choices[0].message.content)
        product_label = (raw.get("product_label") or "").strip()
        raw_ingredients = raw.get("ingredients") or []

        results: List[tuple[str, Optional[str]]] = []
        for item in raw_ingredients:
            key = (item.get("key") or "").strip().lower()
            if key and key != "none" and key in SUPPLEMENT_RULES:
                results.append((key, product_label if product_label and product_label != "none" else None))
        return results
    except Exception:
        pass
    return []


def infer_medications_from_message(message: str) -> Optional[str]:
    """
    자유 입력 메시지에서 갑상선 관련 약물을 추출.
    키워드 매칭 우선, 실패 시 LLM fallback.
    갑상선 무관 약물은 None 반환.
    """
    text = (message or "").strip().lower()
    if not text:
        return None

    _MED_KEYWORD_MAP = {
        # 갑상선 호르몬제 (T4)
        "레보티록신": "레보티록신", "씬지로이드": "레보티록신",
        "씬지록신": "레보티록신", "씬지로신": "레보티록신",
        "신지록신": "레보티록신", "신지로이드": "레보티록신",
        "갑상선약": "레보티록신", "갑상선호르몬": "레보티록신",
        "엘지로이드": "레보티록신", "콤지로이드": "레보티록신",
        "synthroid": "레보티록신", "levothyroxine": "레보티록신",
        "티록신": "레보티록신",
        # 갑상선 호르몬제 (T3)
        "리오티로닌": "리오티로닌", "테트로닌": "리오티로닌",
        "liothyronine": "리오티로닌", "cytomel": "리오티로닌",
        # 항갑상선제
        "메티마졸": "메티마졸", "메티졸": "메티마졸",
        "methimazole": "메티마졸", "tapazole": "메티마졸",
        "프로필티오우라실": "프로필티오우라실", "ptu": "프로필티오우라실",
        "안티로이드": "프로필티오우라실", "propylthiouracil": "프로필티오우라실",
        # 항응고제 (오메가3 상호작용)
        "와파린": "와파린", "warfarin": "와파린", "쿠마딘": "와파린",
        "항응고제": "와파린",
        # 흡수 방해 약물 (레보티록신 복용 시 중요)
        "제산제": "제산제", "탄산칼슘": "칼슘제", "칼슘제": "칼슘제",
        "철분제": "철분제", "철분보충제": "철분제",
    }

    # [1단계] 키워드 매칭 (긴 것 우선)
    sorted_meds = sorted(_MED_KEYWORD_MAP.keys(), key=len, reverse=True)
    for keyword in sorted_meds:
        if keyword in text:
            return _MED_KEYWORD_MAP[keyword]

    # [2단계] DB fallback 추가
    try:
        from domain.mfds.db import normalize_drug_name
        _THYROID_EN_WHITELIST = {
            "levothyroxine": "레보티록신",
            "liothyronine": "리오티로닌",
            "methimazole": "메티마졸",
            "propylthiouracil": "프로필티오우라실",
            "warfarin": "와파린",
            "calcium": "칼슘제",
            "ferrous": "철분제",
        }
        
        # 메시지를 띄어쓰기 단위로 분리 후 각 단어 DB 조회
        for word in text.split():
            en_name = normalize_drug_name(word)
            for key in _THYROID_EN_WHITELIST:
                if key in (en_name or "").lower():
                    return _THYROID_EN_WHITELIST[key]
    except Exception:
        pass

    # LLM fallback: 자유 입력 처리
    try:
        import json as _json
        from domain.consultation.pubmed.openai_client import _get_openai_client
        client = _get_openai_client()
        recognized = [
            "레보티록신", "리오티로닌", "메티마졸", "프로필티오우라실",
            "와파린", "칼슘제", "철분제", "제산제"
        ]
        prompt = (
            f"갑상선 환자 상담 시스템입니다. 아래 문장에서 갑상선 관련 약물을 추출하세요.\n\n"
            f"[사용자 문장]\n{message}\n\n"
            f"[인식 가능한 약물 목록]\n{', '.join(recognized)}\n\n"
            f"규칙:\n"
            f"1. JSON 형식으로만 반환: {{\"medication\": \"약물명\"}}\n"
            f"2. 목록에 있는 약물이 언급되면 해당 약물명을 반환\n"
            f"3. 갑상선 무관 약물이거나 약물이 없으면: {{\"medication\": \"none\"}}\n"
            f"4. 설명 금지."
        )
        response = client.chat.completions.create(
            model="gpt-4o-mini",
            messages=[{"role": "user", "content": prompt}],
            response_format={"type": "json_object"},
            temperature=0,
        )
        raw = _json.loads(response.choices[0].message.content)
        med = (raw.get("medication") or "").strip()
        if med and med != "none":
            return med
    except Exception:
        pass
    return None
