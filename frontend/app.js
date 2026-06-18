document.addEventListener("DOMContentLoaded", () => {
  // Nav handling
  const navBtns = document.querySelectorAll('.nav-btn');
  const sections = document.querySelectorAll('.view-section');

  navBtns.forEach(btn => {
    btn.addEventListener('click', () => {
      navBtns.forEach(b => b.classList.remove('active'));
      sections.forEach(s => s.classList.remove('active'));

      btn.classList.add('active');
      const target = btn.getAttribute('data-target');
      document.getElementById(target).classList.add('active');

      if (target === 'analytics-view') fetchAnalytics();
      if (target === 'profile-view') updateProfileView();
      if (target === 'my-feedback-view') loadMyFeedback();
    });
  });

  const API_BASE = '/api/v1';
  const AUTH_BASE = '/api/auth';

  // Auth Tab Switch
  window.switchAuthTab = (tab) => {
    document.getElementById('patient-auth').style.display = tab === 'patient' ? 'flex' : 'none';
    document.getElementById('doctor-auth').style.display = tab === 'doctor' ? 'flex' : 'none';
    document.getElementById('tab-patient').classList.toggle('active', tab === 'patient');
    document.getElementById('tab-doctor').classList.toggle('active', tab === 'doctor');
  };

  // Auth Helpers
  const getAuthHeaders = () => {
    const token = localStorage.getItem('doctor_token');
    return {
      "Content-Type": "application/json",
      ...(token ? { "Authorization": `Bearer ${token}` } : {})
    };
  };

  const getPatientAuthHeaders = () => {
    const token = localStorage.getItem('patient_token');
    return {
      "Content-Type": "application/json",
      ...(token ? { "Authorization": `Bearer ${token}` } : {})
    };
  };

  const updateAuthState = (loggedIn, name = '', role = 'doctor') => {
    document.getElementById('login-section').style.display = loggedIn ? 'none' : 'block';
    document.getElementById('user-section').style.display = loggedIn ? 'flex' : 'none';
    if (loggedIn) {
      const label = role === 'patient' ? `${name} 환자님` : `${name} 의사님`;
      document.getElementById('logged-in-user').textContent = label;
      if (role === 'doctor') loadDoctorProfile();
    } else {
      localStorage.removeItem('doctor_token');
      localStorage.removeItem('doctor_name');
      localStorage.removeItem('doctor_id');
      localStorage.removeItem('patient_token');
      localStorage.removeItem('patient_name');
      localStorage.removeItem('patient_role');
    }
  };

  const updateProfileView = () => {
    const role = localStorage.getItem('patient_role') || localStorage.getItem('doctor_token') ? 'doctor' : null;
    const patientToken = localStorage.getItem('patient_token');
    const doctorToken = localStorage.getItem('doctor_token');
    const hint = document.getElementById('profile-login-hint');
    const patPanel = document.getElementById('patient-profile-panel');
    const docPanel = document.getElementById('doctor-profile-panel');
    if (patientToken) {
      hint.style.display = 'none';
      patPanel.style.display = 'block';
      docPanel.style.display = 'none';
      loadPatientProfile();
    } else if (doctorToken) {
      hint.style.display = 'none';
      patPanel.style.display = 'none';
      docPanel.style.display = 'block';
      loadDoctorProfile();
    } else {
      hint.style.display = 'block';
      patPanel.style.display = 'none';
      docPanel.style.display = 'none';
    }
  };

  // ── 태그 선택형 필드 초기화 ────────────────────────────────
  // 각 태그 그룹을 초기화. fieldId: hidden input id, multiSelect: 복수선택 여부
  const TAG_FIELDS = [
    { tagsId: "ctx-supplement-tags", fieldId: "ctx-supplement", customWrapId: "ctx-supplement-custom-wrap", customInputId: "ctx-supplement-custom", multiSelect: false },
    { tagsId: "ctx-conditions-tags", fieldId: "ctx-conditions", customWrapId: "ctx-conditions-custom-wrap", customInputId: "ctx-conditions-custom", multiSelect: true },
    { tagsId: "ctx-medications-tags", fieldId: "ctx-medications", customWrapId: "ctx-medications-custom-wrap", customInputId: "ctx-medications-custom", multiSelect: true },
    { tagsId: "ctx-treatment-tags", fieldId: "ctx-treatment", customWrapId: "ctx-treatment-custom-wrap", customInputId: "ctx-treatment-custom", multiSelect: true },
    { tagsId: "ctx-symptoms-tags", fieldId: "ctx-symptoms", customWrapId: "ctx-symptoms-custom-wrap", customInputId: "ctx-symptoms-custom", multiSelect: true },
    { tagsId: "doc-supplement-tags", fieldId: "doc-supplement", customWrapId: "doc-supplement-custom-wrap", customInputId: "doc-supplement-custom", multiSelect: false, panelId: "doc-supplement-panel", displayId: "doc-supplement-display", dgId: "doc-supplement-dg" },
    { tagsId: "doc-conditions-tags", fieldId: "doc-conditions", customWrapId: "doc-conditions-custom-wrap", customInputId: "doc-conditions-custom", multiSelect: true, panelId: "doc-conditions-panel", displayId: "doc-conditions-display", dgId: "doc-conditions-dg" },
    { tagsId: "doc-medications-tags", fieldId: "doc-medications", customWrapId: "doc-medications-custom-wrap", customInputId: "doc-medications-custom", multiSelect: true, panelId: "doc-medications-panel", displayId: "doc-medications-display", dgId: "doc-medications-dg" },
    { tagsId: "doc-treatment-history-tags", fieldId: "doc-treatment-history", customWrapId: "doc-treatment-history-custom-wrap", customInputId: "doc-treatment-history-custom", multiSelect: true, panelId: "doc-treatment-history-panel", displayId: "doc-treatment-history-display", dgId: "doc-treatment-history-dg" },
    { tagsId: "doc-symptoms-diet-tags", fieldId: "doc-symptoms-diet", customWrapId: "doc-symptoms-diet-custom-wrap", customInputId: "doc-symptoms-diet-custom", multiSelect: true, panelId: "doc-symptoms-diet-panel", displayId: "doc-symptoms-diet-display", dgId: "doc-symptoms-diet-dg" },
  ];

  function _syncTagField(config) {
    const tagsEl = document.getElementById(config.tagsId);
    const fieldEl = document.getElementById(config.fieldId);
    const customWrap = document.getElementById(config.customWrapId);
    const customInput = document.getElementById(config.customInputId);
    if (!tagsEl || !fieldEl) return;

    const selected = [];
    const otherActive = tagsEl.querySelector('.tag-btn[data-value="__other__"].selected, .tag-btn--out.selected');

    tagsEl.querySelectorAll(".tag-btn.selected").forEach(btn => {
      if (btn.dataset.value !== "__other__") selected.push(btn.dataset.value);
    });

    // 커스텀 입력값이 있으면 선택된 값 목록에 추가
    if ((otherActive || tagsEl.querySelector('.tag-btn--out.selected')) && customInput?.value.trim()) {
      selected.push(customInput.value.trim());
    }

    fieldEl.value = selected.join(", ");
    // 드롭다운 display 텍스트 업데이트
    if (config.displayId) {
      const displayEl = document.getElementById(config.displayId);
      if (displayEl) {
        if (selected.length > 0) {
          displayEl.textContent = selected.join(", ");
          displayEl.classList.add("has-value");
        } else {
          displayEl.textContent = "클릭하여 선택…";
          displayEl.classList.remove("has-value");
        }
      }
    }
    if (fieldEl.id.startsWith("ctx-")) updatePatientInfoMode?.();
  }

  function initTagField(config) {
    const tagsEl = document.getElementById(config.tagsId);
    const fieldEl = document.getElementById(config.fieldId);
    const customWrap = document.getElementById(config.customWrapId);
    const customInput = document.getElementById(config.customInputId);
    if (!tagsEl) return;

    tagsEl.querySelectorAll(".tag-btn").forEach(btn => {
      btn.addEventListener("click", () => {
        const isOther = btn.dataset.value === "__other__";
        if (!config.multiSelect) {
          // 단일 선택: 다른 버튼 모두 해제
          tagsEl.querySelectorAll(".tag-btn").forEach(b => b.classList.remove("selected"));
        }
        const wasSelected = btn.classList.contains("selected");
        btn.classList.toggle("selected");

        if (isOther || btn.classList.contains('tag-btn--out')) {
          const nowSelected = btn.classList.contains("selected");
          if (customWrap) customWrap.style.display = nowSelected ? "block" : "none";
          if (!nowSelected && customInput) customInput.value = "";
        }
        _syncTagField(config);
      });
    });

    if (customInput) {
      customInput.addEventListener("input", () => _syncTagField(config));
    }
  }

  // 특정 필드에 값을 설정하는 범용 함수 (시나리오 자동채우기용)
  function setTagField(config, value) {
    const tagsEl = document.getElementById(config.tagsId);
    const fieldEl = document.getElementById(config.fieldId);
    const customWrap = document.getElementById(config.customWrapId);
    const customInput = document.getElementById(config.customInputId);
    if (!tagsEl || !fieldEl) return;

    // 전체 초기화
    tagsEl.querySelectorAll(".tag-btn").forEach(b => b.classList.remove("selected"));
    if (customWrap) customWrap.style.display = "none";
    if (customInput) customInput.value = "";
    if (fieldEl) fieldEl.value = "";
    if (!value) return;

    const values = value.split(/[,，]/).map(v => v.trim()).filter(Boolean);
    let hasCustom = false;
    const customValues = [];

    values.forEach(val => {
      // MVP 영양제 한글→영문 매핑
      const SUPP_MAP = {
        "요오드": "iodine", "셀레늄": "selenium", "철분": "iron", "철분제": "iron",
        "비타민d": "vitamin_d", "비타민D": "vitamin_d", "아연": "zinc",
        "마그네슘": "magnesium", "프로바이오틱스": "probiotics"
      };
      const normalized = SUPP_MAP[val] || val;
      const matchBtn = tagsEl.querySelector(`.tag-btn[data-value="${normalized}"]`)
        || tagsEl.querySelector(`.tag-btn[data-value="${val}"]`);
      if (matchBtn) {
        matchBtn.classList.add("selected");
      } else {
        hasCustom = true;
        customValues.push(val);
      }
    });

    if (hasCustom) {
      const otherBtn = tagsEl.querySelector('.tag-btn[data-value="__other__"]')
        || tagsEl.querySelector('.tag-btn--out');
      if (otherBtn) {
        otherBtn.classList.add("selected");
        if (customWrap) customWrap.style.display = "block";
        if (customInput) customInput.value = customValues.join(", ");
      }
    }
    _syncTagField(config);
  }

  function resetTagField(config) {
    setTagField(config, "");
  }

  function getTagFieldConfig(fieldId) {
    return TAG_FIELDS.find(c => c.fieldId === fieldId);
  }

  // 모든 태그 필드 초기화
  TAG_FIELDS.forEach(config => initTagField(config));

  // ── 드롭다운 패널 열기/닫기 ──────────────────────────────
  function closeAllDropdowns(exceptDgId) {
    TAG_FIELDS.filter(c => c.panelId).forEach(c => {
      if (c.dgId === exceptDgId) return;
      const panel = document.getElementById(c.panelId);
      const dg = document.getElementById(c.dgId);
      if (panel) panel.style.display = "none";
      if (dg) dg.classList.remove("open");
    });
  }

  TAG_FIELDS.filter(c => c.panelId).forEach(config => {
    const trigger = document.querySelector(`[data-dg="${config.dgId}"]`);
    const panel = document.getElementById(config.panelId);
    const dg = document.getElementById(config.dgId);
    if (!trigger || !panel || !dg) return;

    trigger.addEventListener("click", (e) => {
      e.stopPropagation();
      const isOpen = dg.classList.contains("open");
      closeAllDropdowns(null);
      if (!isOpen) {
        panel.style.display = "block";
        dg.classList.add("open");
      }
    });
  });

  document.addEventListener("click", (e) => {
    if (!e.target.closest(".tag-dropdown-group")) {
      closeAllDropdowns(null);
    }
  });

  // 의사용 BMI 자동계산
  function updateDocBmi() {
    const h = parseFloat(document.getElementById("doc-height")?.value);
    const w = parseFloat(document.getElementById("doc-weight")?.value);
    const bmiEl = document.getElementById("doc-bmi");
    if (!bmiEl) return;
    if (h > 0 && w > 0) {
      bmiEl.value = (w / ((h / 100) ** 2)).toFixed(1);
    } else {
      bmiEl.value = "";
    }
  }
  document.getElementById("doc-height")?.addEventListener("input", updateDocBmi);
  document.getElementById("doc-weight")?.addEventListener("input", updateDocBmi);

  // Patient Logic
  const chatOutput = document.getElementById("patient-chat-output");
  const patientInput = document.getElementById("patient-input");
  const patientBtn = document.getElementById("patient-btn");

  // 세션 상태 (페이지 새로고침 시 초기화)
  let sessionConditions = "";
  let sessionMedications = "";
  let sessionSupplement = "";  // 한번 인식되면 유지
  let chatHistory = [];
  let lastConsult = null;  // 가장 최근 상담 스냅샷 (피드백 제출에 사용)
  let currentFeedbackTab = 'cases';  // 'cases' | 'general'

  const PATIENT_REQUIRED_CONTEXT = [
    "age",
    "sex",
    "supplement",
    "conditions",
    "medications",
    "currentSupplements",
    "pregnancy"
  ];

  // ── 환자 예시 시나리오 ──────────────────────────────
  const PATIENT_SAMPLE_CASES = [
    {
      id: "P-H1", label: "하시모토+셀레늄",
      title: "기대: personalized / conditional_consider",
      fields: {
        age: "58", sex: "male", supplement: "셀레늄",
        conditions: "갑상선기능저하증, 하시모토 갑상선염",
        medications: "레보티록신", currentSupplements: "비타민D",
        symptoms: "피로, 체중 증가, TPOAb 상승", labs: "TSH 3.8, Free T4 1.1",
        message: "하시모토인데 셀레늄 먹어도 될까요?"
      }
    },
    {
      id: "P-H2", label: "그레이브스+요오드",
      title: "기대: personalized / avoid 또는 contraindicated",
      fields: {
        age: "54", sex: "female", supplement: "요오드",
        conditions: "그레이브스병, 갑상선기능항진증",
        medications: "메티마졸", currentSupplements: "비타민D",
        symptoms: "심계항진, 체중 감소, 안구돌출", labs: "TSH 0.01, Free T4 2.8",
        message: "그레이브스병인데 요오드 영양제 먹어도 될까요?"
      }
    },
    {
      id: "P-H3", label: "저하+철분",
      title: "기대: personalized / conditional (상호작용 안내)",
      fields: {
        age: "61", sex: "female", supplement: "철분",
        conditions: "갑상선기능저하증",
        medications: "레보티록신", currentSupplements: "",
        symptoms: "피로, 창백, 두근거림", labs: "TSH 6.2, Free T4 0.8",
        message: "레보티록신 먹는데 철분제 같이 먹어도 되나요?"
      }
    },
    {
      id: "P-H4", label: "하시모토+비타민D",
      title: "기대: personalized / conditional_consider",
      fields: {
        age: "45", sex: "female", supplement: "비타민D",
        conditions: "하시모토 갑상선염",
        medications: "레보티록신", currentSupplements: "",
        symptoms: "관절통, 우울감, 피로", labs: "TSH 4.5, Free T4 0.9",
        message: "비타민D 결핍인데 보충해도 될까요?"
      }
    },
    {
      id: "P-H5", label: "저하+아연",
      title: "기대: personalized / conditional",
      fields: {
        age: "33", sex: "male", supplement: "아연",
        conditions: "하시모토 갑상선염, 갑상선기능저하증",
        medications: "레보티록신", currentSupplements: "셀레늄",
        symptoms: "피로, 아연 결핍 의심", labs: "TSH 4.1, Free T4 1.0",
        message: "아연 보충제 추가해도 될까요?"
      }
    },
    {
      id: "P-H6", label: "저하+마그네슘",
      title: "기대: personalized / conditional (복용 간격 안내)",
      fields: {
        age: "52", sex: "female", supplement: "마그네슘",
        conditions: "갑상선기능저하증",
        medications: "레보티록신", currentSupplements: "",
        symptoms: "근육 경련, 수면 불편", labs: "TSH 3.2, Free T4 1.1",
        message: "마그네슘 저녁에 먹어도 되나요?"
      }
    },
    {
      id: "P-H7", label: "저하+프로바이오틱스",
      title: "기대: personalized / conditional_consider",
      fields: {
        age: "39", sex: "female", supplement: "프로바이오틱스",
        conditions: "갑상선기능저하증",
        medications: "레보티록신", currentSupplements: "",
        symptoms: "복부 팽만, 변비", labs: "TSH 2.9, Free T4 1.2",
        message: "프로바이오틱스 복용해도 될까요?"
      }
    },
    {
      id: "P-G1", label: "일반모드",
      title: "기대: general (진단/약 없음)",
      fields: {
        age: "", sex: "", supplement: "비타민D",
        conditions: "", medications: "", currentSupplements: "",
        symptoms: "", labs: "",
        message: "비타민D가 뭐에 좋아요?"
      }
    },
    {
      id: "P-F1", scope: "out", label: "오메가3",
      title: "기대: MVP 범위 밖 안내 (POST-MVP)",
      fields: {
        age: "45", sex: "female", supplement: "오메가3",
        conditions: "하시모토 갑상선염",
        medications: "레보티록신", currentSupplements: "",
        symptoms: "피로", labs: "",
        message: "오메가3 먹어도 될까요?"
      }
    },
    {
      id: "P-F2", scope: "out", label: "칼슘",
      title: "기대: MVP 범위 밖 안내 (POST-MVP)",
      fields: {
        age: "61", sex: "female", supplement: "칼슘",
        conditions: "갑상선기능저하증",
        medications: "레보티록신", currentSupplements: "철분",
        symptoms: "피로, 근육 경련", labs: "TSH 4.8, Free T4 0.9",
        message: "레보티록신 먹는데 칼슘제 같이 먹어도 되나요?"
      }
    },
  ];

  function fillPatientScenario(id) {
    const c = PATIENT_SAMPLE_CASES.find(s => s.id === id);
    if (!c) return;
    const set = (elId, val) => {
      const el = document.getElementById(elId);
      if (el) el.value = val;
    };
    set("ctx-age", c.fields.age);
    set("ctx-sex", c.fields.sex);
    set("ctx-current-supplements", c.fields.currentSupplements);
    set("ctx-labs", c.fields.labs);
    set("patient-input", c.fields.message);
    set("ctx-pregnancy", "");
    // 태그 선택형 필드 채우기
    setTagField(getTagFieldConfig("ctx-supplement"), c.fields.supplement);
    setTagField(getTagFieldConfig("ctx-conditions"), c.fields.conditions);
    setTagField(getTagFieldConfig("ctx-medications"), c.fields.medications);
    setTagField(getTagFieldConfig("ctx-symptoms"), c.fields.symptoms);
    updatePatientBmi();
    updatePatientInfoMode();
  }

  function clearPatientScenario() {
    document.querySelectorAll("[id^='ctx-']").forEach(el => {
      if (el.tagName === "SELECT" || el.tagName === "INPUT" || el.tagName === "TEXTAREA") el.value = "";
    });
    // 태그 선택형 필드 초기화
    TAG_FIELDS.filter(c => c.fieldId.startsWith("ctx-")).forEach(resetTagField);
    const input = document.getElementById("patient-input");
    if (input) input.value = "";
    updatePatientBmi();
    updatePatientInfoMode();
  }

  const SOFT_DECISION_TEXT = {
    recommend: "일부 근거에서 도움이 될 가능성이 제시됩니다.",
    conditional_consider: "조건에 따라 고려될 수 있으나 환자 상태 확인이 필요합니다.",
    avoid: "주의가 필요한 정보가 있어 복용 전 전문가 상담이 필요합니다.",
    contraindicated: "자료상 금기 또는 피해야 하는 상황으로 보고된 정보가 있습니다.",
    insufficient_evidence: "현재 확인 가능한 근거 수준은 제한적입니다."
  };

  const getValue = (id) => document.getElementById(id)?.value?.trim() || "";

  const collectPatientContext = () => ({
    age: getValue("ctx-age"),
    sex: getValue("ctx-sex"),
    supplement: getValue("ctx-supplement"),
    conditions: getValue("ctx-conditions"),
    medications: getValue("ctx-medications"),
    currentSupplements: getValue("ctx-current-supplements"),
    pregnancy: getValue("ctx-pregnancy"),
    height: getValue("ctx-height"),
    weight: getValue("ctx-weight"),
    bmi: getValue("ctx-bmi"),
    history: getValue("ctx-history"),
    treatment: getValue("ctx-treatment"),
    symptoms: getValue("ctx-symptoms"),
    labs: getValue("ctx-labs"),
    goal: getValue("ctx-goal")
  });

  const hasContextValue = (ctx, key) => {
    if (key === "pregnancy") return Boolean(ctx.pregnancy);
    return Boolean(ctx[key]);
  };

  const isGeneralInfoMode = (ctx) => {
    const filled = PATIENT_REQUIRED_CONTEXT.filter(key => hasContextValue(ctx, key)).length;
    return filled < 4 || !ctx.supplement || !ctx.conditions || !ctx.medications;
  };

  const updatePatientInfoMode = () => {
    const ctx = collectPatientContext();
    updatePatientBmi();
    const isGeneral = isGeneralInfoMode(ctx);
    const badge = document.getElementById("patient-info-mode-badge");
    const note = document.getElementById("patient-info-mode-note");
    const status = document.getElementById("patient-context-status");
    if (!badge || !note) return;
    badge.classList.toggle("general", isGeneral);
    badge.classList.toggle("specific", !isGeneral);
    badge.textContent = isGeneral ? "일반 정보" : "입력 정보 반영";
    note.textContent = isGeneral
      ? "영양제, 진단명, 복용약을 입력하면 더 구체적으로 답변합니다."
      : "입력한 영양제, 진단명, 복용약을 반영해 답변합니다.";
    if (status) {
      const items = [
        ["영양제", Boolean(ctx.supplement)],
        ["진단명", Boolean(ctx.conditions)],
        ["복용약", Boolean(ctx.medications)]
      ];
      status.innerHTML = items.map(([label, present]) =>
        `<span class="context-status-chip ${present ? "filled" : "missing"}">${label} ${present ? "확인됨" : "미입력"}</span>`
      ).join("");
    }
  };

  // §15.4 백엔드가 실제 적용한 response_mode로 입력 배지를 보정 (클라 미리보기 ↔ 실제 동기화)
  const syncInfoModeBadge = (responseMode) => {
    if (responseMode !== "general" && responseMode !== "personalized") return;
    const badge = document.getElementById("patient-info-mode-badge");
    const note = document.getElementById("patient-info-mode-note");
    if (!badge) return;
    const isGeneral = responseMode === "general";
    badge.classList.toggle("general", isGeneral);
    badge.classList.toggle("specific", !isGeneral);
    badge.textContent = isGeneral ? "일반 정보 (적용됨)" : "입력 정보 반영 (적용됨)";
    if (note) {
      note.textContent = isGeneral
        ? "방금 답변은 일반 성인 기준입니다. 진단명·복용약을 입력하면 개인 맞춤으로 답변합니다."
        : "방금 답변은 입력한 영양제·진단명·복용약을 반영했습니다.";
    }
  };

  const patientContextEntries = (ctx) => [
    ["나이", ctx.age ? `${ctx.age}세` : ""],
    ["성별", displayContextValue("sex", ctx.sex)],
    ["문의 성분", ctx.supplement],
    ["진단명", ctx.conditions],
    ["현재 복용약", ctx.medications],
    ["현재 영양제", ctx.currentSupplements],
    ["임신/수유", displayContextValue("pregnancy", ctx.pregnancy)],
    ["키", ctx.height ? `${ctx.height}cm` : ""],
    ["몸무게", ctx.weight ? `${ctx.weight}kg` : ""],
    ["BMI", ctx.bmi],
    ["병력", ctx.history],
    ["수술력/치료", ctx.treatment],
    ["증상", ctx.symptoms],
    ["검사값", ctx.labs],
    ["복용 목적", ctx.goal]
  ].filter(([, value]) => value);

  const buildPatientBackendMessage = (message, ctx) => {
    const entries = patientContextEntries(ctx);
    if (entries.length === 0) return message;
    const contextText = entries.map(([label, value]) => `${label}: ${value}`).join("; ");
    return `[현재 상담 입력 정보] ${contextText}\n\n[질문] ${message}`;
  };

  const displayContextValue = (key, value) => {
    const maps = {
      sex: { female: "여성", male: "남성", other: "기타/응답 안 함" },
      pregnancy: { pregnant: "임신 중", breastfeeding: "수유 중", planning: "임신 준비 중" }
    };
    return maps[key]?.[value] || value;
  };

  const formatSoftDecision = (value) => {
    if (!value) return "현재 확인 가능한 근거 수준은 제한적입니다.";
    return SOFT_DECISION_TEXT[value] || SOFT_DECISION_TEXT[String(value).toLowerCase()] || String(value);
  };

  // System suggested decision 카드용 — conclusion의 첫 1~2문장만 요약 표시.
  // 상세 전문은 Evidence summary 카드에만 두어 중복을 피한다.
  const decisionHeadline = (data) => {
    const text = (data && data.conclusion ? String(data.conclusion) : "").trim();
    if (!text) return formatSoftDecision(data && data.decision);
    const parts = text.split(/(?<=[.。])\s+/).filter(Boolean);
    return parts.slice(0, 2).join(" ").trim() || text;
  };

  const updatePatientBmi = () => {
    const height = parseFloat(getValue("ctx-height"));
    const weight = parseFloat(getValue("ctx-weight"));
    const bmiEl = document.getElementById("ctx-bmi");
    if (!bmiEl) return;
    if (!height || !weight) {
      bmiEl.value = "";
      return;
    }
    const meters = height / 100;
    const bmi = weight / (meters * meters);
    bmiEl.value = Number.isFinite(bmi) ? bmi.toFixed(1) : "";
  };

  const isOutOfScopeCondition = (text) => /갑상선암|thyroid cancer|goiter|갑상선종|thyroid nodule|갑상선결절|orbitopathy|안병증|thyroidectomy|전절제|반절제/.test(String(text || "").toLowerCase());

  const findDoseText = (data) =>
    data.research_dose_summary ||
    data.study_dose ||
    data.study_doses ||
    data.dose_notes ||
    data.dosing ||
    data.dose_summary ||
    "";

  // §9.2 용량 분리 렌더: research_dose / official_dose_reference 가 있으면 2카드,
  // 없으면 기존 합본(findDoseText) 단일 카드로 fallback.
  const renderDoseCards = (data, emptyText) => {
    const research = data.research_dose;
    const official = data.official_dose_reference;
    if (research || (official && official.text)) {
      let out = "";
      if (research) out += infoCard("연구에서 사용된 용량", research, "evidence-card");
      if (official && official.text) {
        const srcChip = official.source
          ? `<span class="status-chip neutral">출처: ${escapeHtml(official.source)}</span>`
          : "";
        out += `
      <section class="response-card evidence-card">
        <div class="card-title-row">
          <h4>공식 기준·상한</h4>
          ${srcChip}
        </div>
        <p>${escapeHtml(official.text).replace(/\n/g, "<br/>")}</p>
      </section>`;
      }
      return out;
    }
    return infoCard("연구 사용 용량 또는 공식 기준", findDoseText(data) || emptyText, "evidence-card");
  };

  const findEffectsText = (data) =>
    data.reported_effects_summary ||
    data.reported_effects ||
    data.effect_summary ||
    data.reported_benefits ||
    "";

  const findAdverseText = (data) =>
    data.reported_adverse_effects ||
    data.adverse_effects ||
    data.side_effects ||
    "";

  const findLimitationsText = (data) => {
    const arr = data.uncertainty_notes || data.evidence_limitations || data.limitations || data.evidence_gaps;
    if (Array.isArray(arr)) return arr.join("\n") || "";
    return arr || "";
  };

  const buildPatientLevothyroxineNote = (ctx, data) => {
    const combined = [ctx.medications, data.summary, data.chat_message, ...toArray(data.cautions)].join(" ").toLowerCase();
    if (!/levothyroxine|레보티록신|씬지/.test(combined)) return "";
    return "갑상선 호르몬제는 보통 공복 복용과 식사, 다른 약·영양제와의 간격 확인이 중요합니다. 구체적인 복약 간격은 담당의 또는 약사와 상의가 필요합니다.";
  };

  const buildDoctorLevothyroxineNote = (payload) => {
    const combined = [payload.supplement, payload.medications, payload.treatmentHistory, payload.message].join(" ").toLowerCase();
    if (!/levothyroxine|레보티록신|씬지/.test(combined)) return "";
    if (!/iron|철|calcium|칼슘|magnesium|마그네슘|zinc|아연/.test(combined)) {
      return "Levothyroxine 복약 패턴과 공복 복용 유지 여부를 확인해 주세요.";
    }
    return "철분, 칼슘, 마그네슘, 아연 등 일부 미네랄은 levothyroxine 흡수 저해 가능성이 있어 간격 조정 note와 실제 복약 패턴 확인이 필요합니다.";
  };

  const toArray = (value) => {
    if (!value) return [];
    if (Array.isArray(value)) return value.filter(Boolean);
    return [value];
  };

  const missingCard = (title, description = "현재 백엔드 응답에 해당 필드가 없어 표시할 수 없습니다.") => `
    <section class="response-card missing-card">
      <div class="card-title-row">
        <h4>${escapeHtml(title)}</h4>
        <span class="status-chip missing">✕ 미제공</span>
      </div>
      <p>${escapeHtml(description)}</p>
    </section>`;

  const infoCard = (title, body, className = "info-card") => {
    if (!body && body !== 0) return "";
    return `
      <section class="response-card ${className}">
        <h4>${escapeHtml(title)}</h4>
        <p>${escapeHtml(body).replace(/\n/g, "<br/>")}</p>
      </section>`;
  };

  const listCard = (title, items, className = "info-card", emptyText = "") => {
    const values = toArray(items);
    if (values.length === 0) {
      return emptyText ? infoCard(title, emptyText, className) : "";
    }
    return `
      <section class="response-card ${className}">
        <h4>${escapeHtml(title)}</h4>
        <ul class="card-list">${values.map(item => `<li>${escapeHtml(item)}</li>`).join("")}</ul>
      </section>`;
  };

  const renderContextSummaryCard = (ctx) => {
    const entries = patientContextEntries(ctx);
    if (entries.length === 0) {
      return infoCard("현재 입력 정보 요약", "입력된 상담 정보가 거의 없어 일반 정보 중심으로 안내합니다.", "patient-factor-card");
    }
    return `
      <section class="response-card patient-factor-card">
        <h4>현재 입력 정보 요약</h4>
        <dl class="context-summary">
          ${entries.map(([label, value]) => `<div><dt>${escapeHtml(label)}</dt><dd>${escapeHtml(value)}</dd></div>`).join("")}
        </dl>
      </section>`;
  };

  // §12.1 특수군 강조: 나이 입력값으로 소아(<18)/고령(>=65) 파생 (임신/수유는 별도 alert·safety 항목으로 처리)
  const renderSpecialGroupCallout = (ctx) => {
    const ageNum = parseInt(ctx.age, 10);
    if (Number.isNaN(ageNum)) return "";
    let group = "";
    if (ageNum < 18) group = "소아·청소년";
    else if (ageNum >= 65) group = "고령자";
    if (!group) return "";
    return `
      <section class="response-card special-group-callout" role="note" aria-label="특수군 안내">
        <div class="card-title-row">
          <h4>특수군 확인 안내 (${escapeHtml(group)})</h4>
          <span class="status-chip neutral">특수군</span>
        </div>
        <p>${escapeHtml(group)}의 경우 일반 성인과 안전성 기준이 다를 수 있습니다. 해당 성분의 특수군 관련 정보는 별도로 확인이 필요하며, 복용 전 의사 또는 약사와 상담이 필요합니다.</p>
      </section>`;
  };

  const getPatientSafetyItems = (data, ctx) => {
    const items = [
      ...toArray(data.safety_concerns),
      ...toArray(data.cautions)
    ];
    const combinedText = [
      ctx.supplement,
      ctx.medications,
      ctx.currentSupplements,
      ctx.conditions,
      ctx.pregnancy,
      ...items
    ].join(" ").toLowerCase();

    if (/iodine|요오드|다시마|kelp/.test(combinedText)) {
      items.push("요오드 과잉 섭취 가능성은 갑상선 상태에 따라 위험할 수 있어 복용 전 의사 또는 약사와 상담이 필요합니다.");
    }
    if (/selenium|셀레늄|셀렌/.test(combinedText)) {
      items.push("셀레늄은 과량 섭취 시 독성 가능성이 보고되어 총 섭취량 확인이 필요합니다.");
    }
    if (/ashwagandha|아슈와간다|thyrotoxicosis/.test(combinedText)) {
      items.push("일부 허브 성분은 갑상선 기능 항진 양상과 관련된 보고가 있어 전문가 확인이 필요합니다.");
    }
    if (
      /levothyroxine|레보티록신|씬지/.test(combinedText) &&
      /iron|철|칼슘|calcium|마그네슘|magnesium|아연|zinc/.test(combinedText)
    ) {
      items.push("갑상선 호르몬제와 철분·칼슘·마그네슘·아연은 흡수 간섭이 있을 수 있어 복용 간격 확인이 필요합니다.");
    }
    if (ctx.pregnancy) {
      items.push("임신, 수유 또는 임신 준비 중에는 갑상선 상태와 태아/영아 영향을 함께 고려해야 하므로 전문가 상담이 필요합니다.");
    }
    return [...new Set(items)];
  };

  const renderTopWarnings = (topWarnings) => {
    if (!topWarnings || topWarnings.length === 0) return "";
    return topWarnings.map(w => {
      const label = w.severity === "critical" ? "⚠ 중요 경고" : "⚠ 주의";
      return `
        <div class="top-warning-block ${escapeHtml(w.severity)}">
          <span class="warn-label">${label}</span>
          <span class="warn-message">${escapeHtml(w.message)}</span>
          ${w.recommended_action ? `<div class="warn-action">${escapeHtml(w.recommended_action)}</div>` : ""}
        </div>`;
    }).join("");
  };

  const renderIodinePregnancyAlert = (alert) => {
    if (!alert) return "";
    return `
      <section class="response-card iodine-pregnancy-alert" role="alert" aria-label="임신 중 요오드 주의사항">
        <div class="card-title-row">
          <h4>⚠ 임신 중 요오드 — 양면 주의사항</h4>
          <span class="status-chip critical">임신 특이사항</span>
        </div>
        <ul class="iodine-pregnancy-list">
          <li><strong>결핍 위험:</strong> ${escapeHtml(alert.deficiency_risk)}</li>
          <li><strong>과잉 위험:</strong> ${escapeHtml(alert.excess_risk)}</li>
          <li><strong>공식 기준:</strong> ${escapeHtml(alert.official_standard)}</li>
        </ul>
        <div class="iodine-pregnancy-action">${escapeHtml(alert.action)}</div>
      </section>`;
  };

  // §7.2 복용 간격 판정 뱃지 (manage_interaction 케이스, 입력 타이밍 기반)
  const renderRegimenBadge = (ra) => {
    if (!ra || !ra.status || ra.status === "unknown") return "";
    const map = {
      separated: {
        cls: "regimen-ok", icon: "🟢", label: "복용 간격 적절",
        desc: "갑상선 호르몬제와 충분히 떨어진 시간대에 복용하고 계셔서 흡수 간섭 우려가 낮습니다. 현재 일정을 유지하면서 TSH 등 갑상선 수치를 정기적으로 확인하세요.",
      },
      concurrent: {
        cls: "regimen-warn", icon: "🟠", label: "복용 시간 분리 권장",
        desc: "갑상선 호르몬제와 비슷한 시간대에 복용하고 계셔서 흡수에 영향을 줄 수 있습니다. 복용 시간을 최소 4시간 이상 떨어뜨리는 것이 도움이 됩니다(담당의·약사 확인).",
      },
    };
    const m = map[ra.status];
    if (!m) return "";
    const t = (ra.lt4_hour != null && ra.supplement_hour != null)
      ? `호르몬제 ~${ra.lt4_hour}시 / 영양제 ~${ra.supplement_hour}시` : "";
    return `
      <section class="response-card regimen-badge-card ${m.cls}" role="note" aria-label="복용 간격 판정">
        <div class="regimen-badge-head">
          <span class="regimen-badge-icon">${m.icon}</span>
          <strong>${m.label}</strong>
          ${t ? `<span class="regimen-badge-time">${escapeHtml(t)}</span>` : ""}
        </div>
        <p>${escapeHtml(m.desc)}</p>
      </section>`;
  };

  const renderPatientActionBar = () => `
    <div class="patient-action-bar" aria-label="상담 후 다음 작업">
      <button type="button" class="secondary-btn mini" data-patient-action="context">추가 정보 입력</button>
      <button type="button" class="secondary-btn mini" data-patient-action="continue">질문 이어가기</button>
      <button type="button" class="secondary-btn mini" data-patient-action="feedback">피드백 남기기</button>
    </div>`;

  // §15.4 응답에 온 *실제* response_mode를 환자에게 명시 (general이면 한계 안내)
  const renderResponseModeBanner = (data) => {
    if (!data || data.response_mode !== "general") return "";
    return `
      <section class="response-card mode-banner-general" role="note">
        <div class="card-title-row">
          <h4>ℹ️ 일반 정보 모드</h4>
          <span class="status-chip general">general</span>
        </div>
        <p>현재 입력 정보가 제한적이라 <strong>일반 성인 기준 정보</strong>만 제공됩니다. 개인 맞춤 판단을 위해서는 진단명·복용약·검사값·임신/수유 여부 등의 추가 정보가 필요합니다.</p>
      </section>`;
  };

  const renderPatientResponse = (data, ctx) => {
    if (data.can_take === "정보필요") {
      const suppDisplay = data.identified_supplement_display || data.identified_supplement || null;
      let h = `<div class="patient-response-stack">`;
      if (suppDisplay) {
        h += `<div class="mode-callout"><span class="mode-badge general">${escapeHtml(suppDisplay)} 인식됨</span></div>`;
      }
      if (data.summary) h += infoCard("안내", data.summary, "info-card");
      const candidates = toArray(data.clarification_candidates);
      if (candidates.length) {
        h += `
        <section class="response-card info-card">
          <h4>제품 후보 — 클릭해서 선택</h4>
          <div class="candidate-chips">
            ${candidates.map(c => `<button type="button" class="candidate-chip" data-candidate="${escapeHtml(c)}">${escapeHtml(c)}</button>`).join("")}
          </div>
        </section>`;
      }
      const actions = toArray(data.next_actions);
      if (actions.length) h += listCard("추가 정보 요청", actions, "counseling-card", "");
      h += renderPatientActionBar();
      h += `</div>`;
      return h;
    }

    const safetyItems = getPatientSafetyItems(data, ctx);
    const levothyroxineNote = buildPatientLevothyroxineNote(ctx, data);
    if (levothyroxineNote) safetyItems.unshift(levothyroxineNote);
    let html = `<div class="patient-response-stack">`;
    html += renderResponseModeBanner(data);
    html += renderTopWarnings(data.top_warnings);
    html += renderIodinePregnancyAlert(data.iodine_pregnancy_alert);

    const suppChip = data.identified_supplement_display || data.identified_supplement;
    const condChip = data.identified_conditions;
    if (suppChip || condChip) {
      html += `<div class="recognized-chips">`;
      if (suppChip) html += `<span class="status-chip supplement">${escapeHtml(suppChip)}</span>`;
      if (condChip) html += `<span class="status-chip condition">${escapeHtml(condChip)}</span>`;
      html += `</div>`;
    }

    // §7.2 복용 간격 뱃지 — 인식 칩 바로 아래(상단 강조)
    html += renderRegimenBadge(data.regimen_assessment);

    if (isOutOfScopeCondition(ctx.conditions) || isOutOfScopeCondition(ctx.history) || isOutOfScopeCondition(ctx.treatment)) {
      html += infoCard(
        "초기 범위 안내",
        "현재 입력된 질환 또는 치료 이력에는 초기 알파 범위 밖의 항목이 포함될 수 있습니다. 이 화면은 Hashimoto thyroiditis, hypothyroidism, Graves' disease, hyperthyroidism 중심의 일반 근거를 우선 제공합니다.",
        "regulatory-note-card"
      );
    }

    // §16.1 출력 순서: 안전성 경고 → 판단 문구(결론) → 근거 수준 → 위험/주의 →
    // 복용약·특수군 확인 → 전문가 상담 → (보조 상세) → 참고 자료 수준

    // 안전성 경고 (§7.4 — critical safety warning 최우선 유지)
    html += listCard(
      "안전성 경고",
      safetyItems,
      "safety-warning-card",
      "현재 응답에서 명확한 안전성 경고는 확인되지 않았습니다. 다만 갑상선 질환, 복용약, 임신/수유 여부에 따라 판단이 달라질 수 있습니다."
    );

    // 특수군 안내 (§12.1 — 소아/고령 강조)
    html += renderSpecialGroupCallout(ctx);

    // 판단 문구 — 핵심 결론을 상단으로 (§16.1 ①)
    const decisionValue = data.decision || data.can_take;
    html += `
      <section class="response-card decision-tone-card">
        <div class="card-title-row">
          <h4>판단 문구</h4>
          <span class="status-chip decision">완화 표시</span>
        </div>
        <p>${escapeHtml(formatSoftDecision(decisionValue))}</p>
      </section>`;

    // 근거 수준 (§16.1 ②)
    html += infoCard("근거 수준", data.evidence_level || data.evidence_summary || "현재 확인 가능한 근거 수준은 제한적입니다.", "evidence-card");

    // 위험 또는 주의사항 (§16.1 ③)
    html += listCard("위험 또는 주의사항", data.cautions, "safety-warning-card", "응답에 별도 주의사항 필드는 제공되지 않았습니다.");

    // 복용약/특수군 확인 필요 (§16.1 ④)
    html += listCard(
      "복용약/특수군 확인 필요 사항",
      data.patient_factors,
      "patient-factor-card",
      "레보티록신 복용 여부, 임신/수유 여부, 소아/고령자 여부, 현재 복용 중인 약과 영양제를 전문가와 함께 확인하는 것이 필요합니다."
    );

    // 전문가 상담 권고 (§16.1 ⑤)
    html += listCard(
      "전문가 상담 권고",
      data.next_actions || data.counseling_points,
      "counseling-card",
      "해당 성분은 개인의 진단, 검사값, 복용약에 따라 판단이 달라질 수 있어 복용 전 의사 또는 약사와 상담이 필요합니다."
    );

    // ── 보조 상세 정보 (결론 뒤로 배치) ──
    html += renderContextSummaryCard(ctx);
    html += renderDoseCards(
      data,
      "현재 응답에 연구 사용 용량 또는 공식 기준 필드가 없습니다. 개인별 적정 용량은 진단, 검사값, 복용약에 따라 달라질 수 있어 담당의와 상의가 필요합니다."
    );
    html += infoCard(
      "보고된 효과 및 부작용",
      [findEffectsText(data), findAdverseText(data)].filter(Boolean).join("\n") || "현재 응답에 보고된 효과/부작용 요약 필드가 부족합니다. 개별 연구와 공식 자료를 함께 확인하는 것이 필요합니다.",
      "regulatory-note-card"
    );
    const uncertaintyItems = toArray(data.uncertainty_notes);
    if (uncertaintyItems.length) {
      html += listCard("응답 한계 및 주의", uncertaintyItems, "regulatory-note-card", "");
    }
    html += infoCard(
      "근거의 한계",
      findLimitationsText(data) || "갑상선 질환자 대상 근거가 충분하지 않거나, 연구 규모와 대상자 특성이 제한적일 수 있습니다.",
      "regulatory-note-card"
    );

    if (data.chat_message || data.summary) {
      html += infoCard("참고 설명", data.chat_message || data.summary, "info-card");
    }

    // 참고 근거 또는 자료 수준 (§16.1 ⑥ — 맨 아래) + §11.2 출처 수준 구분 표시
    const evidenceSummaryText = data.evidence_summary || "현재 응답에 별도 참고 근거 요약이 없거나 제한적으로 제공되었습니다.";
    const sourceLevelNote = "표시된 정보는 공식 가이드라인·규제 자료·임상 연구 근거를 우선합니다. 일반 건강정보(예: 일반 웹 정보) 수준의 설명이 포함된 경우, 이는 가이드라인·임상 연구 근거가 아닌 보조 설명입니다.";
    html += infoCard(
      "참고 근거 또는 자료 수준",
      `${evidenceSummaryText}\n\n${sourceLevelNote}`,
      "evidence-card"
    );
    html += renderPatientActionBar();
    html += `</div>`;
    return html;
  };

  const hasOwn = (obj, key) => Object.prototype.hasOwnProperty.call(obj || {}, key);

  const fieldListOrMissing = (data, key, title, className, emptyText) => {
    if (!hasOwn(data, key)) return missingCard(title, `백엔드 응답에 ${key} 필드가 없습니다.`);
    return listCard(title, data[key], className, emptyText);
  };

  const fieldTextOrMissing = (data, key, title, className) => {
    if (!hasOwn(data, key)) return missingCard(title, `백엔드 응답에 ${key} 필드가 없습니다.`);
    return infoCard(title, data[key] || "응답 필드는 제공됐지만 표시할 내용이 비어 있습니다.", className);
  };

  const renderDoctorEvidenceSummary = (data) => {
    const pieces = [];
    if (data.evidence_level) pieces.push(`근거 수준: ${data.evidence_level}`);
    if (data.evidence_summary) pieces.push(data.evidence_summary);
    else if (data.conclusion) pieces.push(data.conclusion);
    if (pieces.length === 0) {
      return missingCard("Evidence summary", "백엔드 응답에 evidence_summary, evidence_level, conclusion 필드가 충분히 제공되지 않았습니다.");
    }
    return infoCard("Evidence summary", pieces.join("\n"), "evidence-card");
  };

  const renderSystemDifferenceCard = (data) => {
    const systemDecision = data.system_suggested_decision || data.decision || "";
    const physicianDecision = data.physician_adjusted_decision || data.physician_adjusted_note || "";
    if (!hasOwn(data, "system_suggested_decision") && !hasOwn(data, "physician_adjusted_decision") && !hasOwn(data, "physician_adjusted_note")) {
      return missingCard("의사 판단과 시스템 근거 간 차이", "백엔드 응답에 system_suggested_decision 또는 physician_adjusted_decision 관련 필드가 없습니다.");
    }
    const lines = [
      systemDecision ? `시스템 제안: ${systemDecision}` : "",
      physicianDecision ? `의사 조정/메모: ${physicianDecision}` : "",
    ].filter(Boolean);
    return infoCard("의사 판단과 시스템 근거 간 차이", lines.join("\n") || "비교 가능한 의사 조정 정보가 없습니다.", "counseling-card");
  };

  const renderPubMedDetails = (data) => {
    const evList = toArray(data.evidence_summaries);
    if (!hasOwn(data, "evidence_summaries")) {
      return missingCard("PubMed details", "백엔드 응답에 evidence_summaries 필드가 없습니다.");
    }

    if (evList.length === 0) {
      return `
        <section class="response-card pubmed-details-card">
          <div class="card-title-row">
            <h4>PubMed details</h4>
            <span class="status-chip neutral">0건</span>
          </div>
          <p>PubMed 검색 결과가 없거나 관련 논문을 찾지 못했습니다.</p>
        </section>`;
    }

    return `
      <section class="response-card pubmed-details-card">
        <div class="card-title-row">
          <h4>PubMed details</h4>
          <span class="status-chip neutral">${evList.length}건</span>
        </div>
        <div class="pubmed-list">
          ${evList.map((ev, i) => {
      const pmid = ev.pmid ? String(ev.pmid) : "";
      const pmidHtml = pmid
        ? `<a href="https://pubmed.ncbi.nlm.nih.gov/${encodeURIComponent(pmid)}/" target="_blank" rel="noopener noreferrer">${escapeHtml(pmid)}</a>`
        : "PMID 없음";
      const meta = [
        ev.year,
        ev.journal,
        ev.evidence_level ? `근거: ${ev.evidence_level}` : ""
      ].filter(Boolean).map(escapeHtml).join(" · ");
      return `
              <details class="pubmed-item">
                <summary>
                  <span>${i + 1}. ${escapeHtml(ev.title || "(제목 없음)")}</span>
                  <small>${pmidHtml}${meta ? ` · ${meta}` : ""}</small>
                </summary>
                ${ev.abstract_snippet ? `<p>${escapeHtml(ev.abstract_snippet)}</p>` : `<p>초록 snippet은 제공되지 않았습니다.</p>`}
              </details>`;
    }).join("")}
        </div>
      </section>`;
  };

  // 6-class 결정 한글 라벨 (의사 추적 카드용 — 내부값 그대로 + 글로스)
  const DECISION_KO = {
    recommend: "권고", conditional_consider: "조건부 고려", manage_interaction: "복용관리(상호작용)",
    avoid: "회피", contraindicated: "금기", insufficient_evidence: "근거 보류"
  };

  // 결정론 추적 카드 — "판정은 LLM이 아니라 규칙"을 의사 UI에 가시화
  const renderDecisionTrace = (data) => {
    const t = data && data.decision_trace;
    if (!t) return "";
    const decKo = DECISION_KO[t.decision] || t.decision;
    const chain = (t.applied_rules || [])
      .map((r) => `<span class="trace-step">${escapeHtml(r.label || r.code || "")}</span>`)
      .join('<span class="trace-arrow">→</span>');
    const adjusted = t.physician_adjusted
      ? `<li>시스템 제안(성향조정 전): <strong>${escapeHtml(DECISION_KO[t.system_suggested] || t.system_suggested || "-")}</strong> → 적용: <strong>${escapeHtml(decKo)}</strong></li>`
      : "";
    return `
      <section class="response-card decision-trace-card" aria-label="판정 근거 추적">
        <div class="card-title-row">
          <h4>🔎 판정 근거 (결정론 추적)</h4>
          <span class="status-chip decision">${escapeHtml(decKo)} · ${escapeHtml(t.decision)}</span>
        </div>
        <div class="trace-chain">${chain || '<span class="trace-step">근거 정보 없음</span>'}</div>
        <ul class="trace-meta">
          <li>근거 수준: <strong>${escapeHtml(t.evidence_level || "-")}</strong></li>
          <li>안전 플래그: <strong>${Number(t.safety_flags || 0)}건</strong></li>
          ${adjusted}
        </ul>
        <p class="trace-note">※ ${escapeHtml(t.note || "임상 판정은 규칙·안전검사가 내립니다. LLM은 문장 생성만 합니다.")}</p>
      </section>`;
  };

  const renderDoctorResponse = (data) => {
    const doctorPayload = {
      supplement: getValue("doc-supplement"),
      medications: getValue("doc-medications"),
      treatmentHistory: getValue("doc-treatment-history"),
      message: getValue("doc-message")
    };
    let html = `<div class="doctor-response-stack">`;
    html += fieldListOrMissing(
      data,
      "safety_concerns",
      "안전성 경고",
      "safety-warning-card",
      "응답 필드는 제공됐지만 별도 안전성 경고는 없습니다."
    );

    html += renderDecisionTrace(data);

    html += `
      <section class="response-card decision-tone-card">
        <div class="card-title-row">
          <h4>System suggested decision</h4>
          <span class="status-chip decision">내부값: ${escapeHtml(data.decision || "없음")}</span>
        </div>
        <p>${escapeHtml(decisionHeadline(data))}</p>
      </section>`;

    if (data.physician_adjusted_decision) {
      html += infoCard(
        "의사 성향 조정 결과",
        `시스템 제안: ${data.system_suggested_decision || "-"} → 의사 성향 적용 후: ${data.physician_adjusted_decision}`,
        "counseling-card"
      );
    }

    // §16.2 ②: Evidence summary를 규제 note보다 앞에 배치
    html += renderDoctorEvidenceSummary(data);
    // §16.2 ③: 주요 근거/문헌 (key_references) — guideline 우선 정렬 상위 문헌
    html += fieldListOrMissing(
      data,
      "key_references",
      "주요 근거/문헌",
      "evidence-card",
      "응답 필드는 제공됐지만 큐레이션된 핵심 문헌이 없습니다."
    );
    // §10.3: 가이드라인 vs 개별 논문 충돌 — 있을 때만 전용 카드로 명시
    if (data.guideline_conflict) {
      html += infoCard("⚖ 근거 간 차이 (가이드라인 vs 연구)", data.guideline_conflict, "regulatory-note-card");
    }
    html += fieldTextOrMissing(data, "regulatory_note", "Regulatory note", "regulatory-note-card");
    html += renderDoseCards(
      data,
      "백엔드 응답에 연구 사용 용량 또는 공식 기준 요약 필드가 없습니다."
    );
    html += infoCard(
      "보고된 효과 및 부작용",
      [findEffectsText(data), findAdverseText(data)].filter(Boolean).join("\n") || "백엔드 응답에 보고된 효과/부작용 필드가 없습니다.",
      "regulatory-note-card"
    );
    html += fieldListOrMissing(
      data,
      "patient_factors",
      "Patient factors",
      "patient-factor-card",
      "응답 필드는 제공됐지만 별도 환자요인은 없습니다."
    );
    html += infoCard(
      "Levothyroxine interaction note",
      buildDoctorLevothyroxineNote(doctorPayload) || "Levothyroxine 관련 상호작용 note가 필요한 입력은 현재 확인되지 않았습니다.",
      "regulatory-note-card"
    );
    html += fieldListOrMissing(
      data,
      "counseling_points",
      "Counseling points",
      "counseling-card",
      "응답 필드는 제공됐지만 별도 상담 포인트는 없습니다."
    );
    html += fieldListOrMissing(
      data,
      "monitoring_parameters",
      "Monitoring parameters",
      "regulatory-note-card",
      "응답 필드는 제공됐지만 별도 추적 검사 항목은 없습니다."
    );
    html += infoCard(
      "근거의 한계",
      findLimitationsText(data) || "가이드라인, RCT, 관찰연구 간 근거 수준 차이와 갑상선 질환자 대상 직접 근거 부족 가능성을 함께 해석해야 합니다.",
      "regulatory-note-card"
    );
    html += renderSystemDifferenceCard(data);
    html += renderPubMedDetails(data);
    html += `
      <section class="response-card physician-note-card">
        <div class="card-title-row">
          <h4>의사 메모 (Physician note)</h4>
          <span class="status-chip neutral">§14.4</span>
        </div>
        ${data.physician_note
          ? `<p class="physician-note-echoed">${escapeHtml(data.physician_note)}</p>`
          : `<textarea id="physician-note-input" class="physician-note-textarea" rows="3" placeholder="이번 상담에 대한 임상 메모를 입력하세요 (다음 요청 시 physician_note 필드로 전송됩니다)…"></textarea>`
        }
      </section>`;
    html += `</div>`;
    return html;
  };

  const _extractConditions = (text) => {
    if (/하시모토|자가면역.?갑상선/.test(text)) return "하시모토 갑상선염";
    if (/그레이브스/.test(text)) return "그레이브스병";
    if (/갑상선기능저하|기능저하증/.test(text)) return "갑상선기능저하증";
    if (/갑상선기능항진|기능항진증/.test(text)) return "갑상선기능항진증";
    if (/갑상선암/.test(text)) return "갑상선암";
    return "";
  };

  const _parseLabValues = (labText) => {
    if (!labText || !labText.trim()) return undefined;
    const result = {};
    const patterns = [
      [/TSH\s*[:\s]\s*([\d.]+)/i, "TSH"],
      [/Free\s*T4\s*[:\s]\s*([\d.]+)/i, "freeT4"],
      [/Free\s*T3\s*[:\s]\s*([\d.]+)/i, "freeT3"],
      [/ferritin\s*[:\s]\s*([\d.]+)/i, "ferritin"],
      [/25[-\s]?OH\s*(?:Vit(?:amin)?\s*)?D\s*[:\s]\s*([\d.]+)/i, "25_oh_vitamin_d"],
      [/Calcium\s*[:\s]\s*([\d.]+)/i, "calcium"],
      [/Zinc\s*[:\s]\s*([\d.]+)/i, "zinc"],
      [/Magnesium\s*[:\s]\s*([\d.]+)/i, "magnesium"],
      [/Selenium\s*[:\s]\s*([\d.]+)/i, "selenium"],
    ];
    for (const [regex, key] of patterns) {
      const m = labText.match(regex);
      if (m) result[key] = parseFloat(m[1]);
    }
    return Object.keys(result).length > 0 ? result : undefined;
  };

  const _extractMedications = (text) => {
    // 레보티록신 계열 (T4 호르몬)
    if (/레보티록신|씬지로이드|씬지|씬지로신|씬지록신|엘지로이드|콤지로이드/.test(text)) return "레보티록신";

    // 리오티로닌 계열 (T3 호르몬)
    if (/리오티로닌|테트로닌|lithothyronine|triiodothyronine/.test(text)) return "리오티로닌";

    // 메티마졸 계열
    if (/메티마졸|메티졸|부광메티마졸/.test(text)) return "메티마졸";

    // 프로필티오우라실 계열
    if (/프로필티오우라실|PTU|안티로이드|티우라실|로치실/.test(text)) return "프로필티오우라실";

    // 방사성요오드 치료
    if (/방사성요오드|RAI|방사성 요오드|방사선 요오드/.test(text)) return "방사성요오드";

    // 갑상선 수술
    if (/수술|절제|절제술|수술 후|수술했|수술한/.test(text)) return "갑상선 수술";

    return "";
  };

  const appendMessage = (text, type, isHtml = false) => {
    const div = document.createElement("div");
    div.className = `message ${type}`;
    if (isHtml) div.innerHTML = text;
    else div.textContent = text;
    chatOutput.appendChild(div);
    chatOutput.scrollTop = chatOutput.scrollHeight;
  };

  chatOutput.addEventListener("click", (event) => {
    // §6.2 재질문 후보 칩 — 클릭 시 해당 제품명으로 재질의
    const candBtn = event.target.closest("[data-candidate]");
    if (candBtn) {
      patientInput.value = candBtn.dataset.candidate;
      patientBtn.click();
      return;
    }
    const actionBtn = event.target.closest("[data-patient-action]");
    if (!actionBtn) return;
    const action = actionBtn.dataset.patientAction;
    if (action === "context") {
      document.querySelector(".patient-context-panel")?.scrollIntoView({ behavior: "smooth", block: "start" });
      document.getElementById("ctx-supplement")?.focus({ preventScroll: true });
      return;
    }
    if (action === "continue") {
      patientInput.focus();
      patientInput.scrollIntoView({ behavior: "smooth", block: "center" });
      return;
    }
    if (action === "feedback") {
      document.getElementById("nav-feedback")?.click();
      requestAnimationFrame(() => {
        document.getElementById("general-feedback-message")?.focus();
      });
    }
  });

  patientBtn.addEventListener("click", async () => {
    const msg = patientInput.value.trim();
    if (!msg) return;
    const patientContext = collectPatientContext();
    updatePatientInfoMode();

    appendMessage(msg, "user");
    patientInput.value = "";

    // 실시간 검색 로딩 메시지
    const loadingId = "loading-" + Date.now();
    const loadingDiv = document.createElement("div");
    loadingDiv.id = loadingId;
    loadingDiv.className = "message agent loading";
    loadingDiv.innerHTML = `<span class="typing-indicator">분석 중...</span>`;
    chatOutput.appendChild(loadingDiv);
    chatOutput.scrollTop = chatOutput.scrollHeight;

    try {
      // 현재 메시지에서 conditions/medications 추출해 세션 업데이트 (유연한 덮어쓰기 허용)
      const detectedCond = _extractConditions(msg);
      const detectedMed = _extractMedications(msg);
      if (patientContext.conditions) sessionConditions = patientContext.conditions;
      else if (detectedCond) sessionConditions = detectedCond;
      if (patientContext.medications) sessionMedications = patientContext.medications;
      else if (detectedMed) sessionMedications = detectedMed;
      if (patientContext.supplement) sessionSupplement = patientContext.supplement;

      // 히스토리에 사용자 메시지 추가
      chatHistory.push({
        role: "user",
        message: msg,
        supplement: sessionSupplement || undefined,
        conditions: sessionConditions || undefined,
        medications: sessionMedications || undefined,
      });

      const res = await fetch(`${API_BASE}/patient/thyroid-chat`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          message: buildPatientBackendMessage(msg, patientContext),
          supplement: sessionSupplement || undefined,
          conditions: patientContext.conditions || sessionConditions || undefined,
          medications: patientContext.medications || sessionMedications || undefined,
          history: chatHistory.slice(-6),
          use_pubmed: false,
          age: patientContext.age ? parseInt(patientContext.age) : undefined,
          sex: patientContext.sex || undefined,
          symptoms: patientContext.symptoms
            ? patientContext.symptoms.split(/[,;，]/).map(s => s.trim()).filter(Boolean)
            : undefined,
          current_supplements: patientContext.currentSupplements || undefined,
          lab_values: _parseLabValues(patientContext.labs),
          risk_factors: patientContext.pregnancy && patientContext.pregnancy !== "none"
            ? [patientContext.pregnancy]
            : undefined,
        })
      });
      const data = await res.json();

      // 응답에서 세션 정보 업데이트 (백엔드의 최신 분석 결과로 강제 동기화)
      if (data.identified_supplement) {
        sessionSupplement = data.identified_supplement;
      }
      if (data.identified_medications) {
        sessionMedications = data.identified_medications;
      }

      // 응답 후 히스토리에 AI 메시지 추가
      chatHistory.push({
        role: "assistant",
        message: data.chat_message || data.summary,
        supplement: sessionSupplement || undefined,
        conditions: sessionConditions || undefined,
        medications: sessionMedications || undefined,
      });

      const html = renderPatientResponse(data, patientContext);

      // §15.4 입력 배지를 백엔드가 실제 적용한 response_mode로 동기화
      // (클라 미리보기와 백엔드 판정이 다를 수 있음 — 예: 자동 general 강등)
      syncInfoModeBadge(data.response_mode);

      // 로딩 메시지를 결과로 대체
      const targetDiv = document.getElementById(loadingId);
      targetDiv.classList.remove("loading");
      targetDiv.classList.add("structured-response");
      targetDiv.innerHTML = html;
    } catch (e) {
      const targetDiv = document.getElementById(loadingId);
      targetDiv.classList.remove("loading");
      targetDiv.classList.add("structured-response");
      targetDiv.innerHTML = renderStateCard(
        "상담 요청을 완료하지 못했습니다",
        "네트워크 또는 서버 상태를 확인한 뒤 다시 전송해 주세요. 입력한 상담 정보는 화면에 유지됩니다.",
        "error"
      );
      console.error(e);
    }
  });

  patientInput.addEventListener("keyup", e => {
    if (e.key === "Enter") patientBtn.click();
  });

  document.querySelectorAll("[id^='ctx-']").forEach(el => {
    el.addEventListener("input", updatePatientInfoMode);
    el.addEventListener("change", updatePatientInfoMode);
  });
  updatePatientInfoMode();

  function escapeHtml(value) {
    return String(value ?? "")
      .replace(/&/g, "&amp;")
      .replace(/</g, "&lt;")
      .replace(/>/g, "&gt;")
      .replace(/"/g, "&quot;")
      .replace(/'/g, "&#39;");
  }

  function renderStateCard(title, body, tone = "info") {
    const role = tone === "error" ? "alert" : "status";
    return `
      <section class="state-card ${tone}" role="${role}" aria-live="${tone === "error" ? "assertive" : "polite"}">
        <h4>${escapeHtml(title)}</h4>
        <p>${escapeHtml(body)}</p>
      </section>
    `;
  }

  // 긴 의사 분석 대기 중 단계형 진행 피드백.
  // 백엔드는 단일 요청/응답이라 실제 진행률을 알 수 없으므로, orchestrator 파이프라인
  // 단계를 타이머로 순차 강조한다. 응답 도착 시 stop()으로 정지(결과 렌더는 호출부가 담당).
  function startDoctorProgress(target, enhanced) {
    const steps = enhanced
      ? ["환자 프로파일 구성", "안전성 규칙 검사", "PubMed 근거 검색", "LLM 재랭킹·논문 확장", "임상 판정 구성"]
      : ["환자 프로파일 구성", "안전성 규칙 검사", "PubMed 근거 검색", "임상 판정 구성"];
    const stepInterval = enhanced ? 2200 : 1200;
    let current = 0;

    const render = () => {
      const items = steps.map((label, i) => {
        const state = i < current ? "done" : (i === current ? "active" : "pending");
        const mark = state === "done" ? "✓" : "";
        return `<li class="progress-step ${state}"><span class="progress-step-mark">${mark}</span><span class="progress-step-label">${escapeHtml(label)}</span></li>`;
      }).join("");
      target.innerHTML = `
        <section class="state-card loading doctor-progress" role="status" aria-live="polite">
          <h4>분석 중<span class="progress-dots"></span></h4>
          <p>전문 문헌과 임상 입력값을 바탕으로 결과를 구성하고 있습니다.${enhanced ? " 고급 검색은 시간이 더 소요될 수 있습니다." : ""}</p>
          <ul class="progress-steps">${items}</ul>
        </section>`;
    };

    render();
    const timer = setInterval(() => {
      if (current < steps.length - 1) {
        current += 1;
        render();
      }
    }, stepInterval);

    return { stop() { clearInterval(timer); } };
  }

  // 의사 결과 내보내기 — 복사(클립보드) / 인쇄(라이트 테마 별도 창)
  const copyDoctorResult = async () => {
    const el = document.getElementById("doctor-output");
    const text = el?.innerText?.trim();
    const btn = document.getElementById("doctor-copy-btn");
    if (!text) return;
    try {
      await navigator.clipboard.writeText(text);
      if (btn) {
        const orig = btn.textContent;
        btn.textContent = "복사됨";
        btn.disabled = true;
        setTimeout(() => { btn.textContent = orig; btn.disabled = false; }, 1500);
      }
    } catch (_) {
      alert("클립보드 복사에 실패했습니다. 결과를 직접 선택해 복사해 주세요.");
    }
  };

  const printDoctorResult = () => {
    const content = document.getElementById("doctor-output")?.innerHTML;
    if (!content) return;
    const win = window.open("", "_blank", "width=820,height=1000");
    if (!win) {
      alert("팝업이 차단되어 인쇄 창을 열 수 없습니다. 팝업을 허용한 뒤 다시 시도해 주세요.");
      return;
    }
    const today = new Date().toLocaleDateString("ko-KR");
    win.document.write(`<!DOCTYPE html><html lang="ko"><head><meta charset="utf-8">
      <title>갑상선 임상 판정 리포트</title>
      <style>
        body { font-family: 'Inter', system-ui, sans-serif; color: #1e293b; line-height: 1.6; margin: 32px; }
        h1 { font-size: 1.3rem; margin: 0 0 4px; }
        .meta { color: #64748b; font-size: 0.82rem; margin-bottom: 20px; border-bottom: 1px solid #e2e8f0; padding-bottom: 12px; }
        section { border: 1px solid #e2e8f0; border-radius: 8px; padding: 12px 14px; margin-bottom: 12px; break-inside: avoid; }
        h4 { margin: 0 0 6px; font-size: 0.98rem; color: #0f172a; }
        p, li { font-size: 0.9rem; color: #334155; }
        ul { margin: 6px 0 0 18px; padding: 0; }
        .safety-warning-card { border-color: #fca5a5; background: #fef2f2; }
        .decision-tone-card { border-color: #5eead4; background: #f0fdfa; }
        .status-chip { display: inline-block; font-size: 0.72rem; padding: 1px 8px; border: 1px solid #cbd5e1; border-radius: 999px; color: #475569; }
        a { color: #0d9488; }
        .disclaimer { margin-top: 20px; font-size: 0.76rem; color: #64748b; border-top: 1px solid #e2e8f0; padding-top: 12px; }
      </style></head>
      <body>
        <h1>갑상선 임상 판정 리포트</h1>
        <div class="meta">생성일: ${today} · 본 리포트는 의료 진단·처방을 대체하지 않는 의사결정 지원 자료입니다.</div>
        ${content}
        <div class="disclaimer">⚠️ 제공 정보는 참고용이며, 복용 전 반드시 전문의와 상담하시기 바랍니다.</div>
      </body></html>`);
    win.document.close();
    win.focus();
    win.print();
  };

  document.getElementById("doctor-copy-btn")?.addEventListener("click", copyDoctorResult);
  document.getElementById("doctor-print-btn")?.addEventListener("click", printDoctorResult);

  // ── 의사 예시 시나리오 ──────────────────────────────
  const DOC_SAMPLE_CASES = [
    {
      id: "D-H1", scope: "mvp", label: "요오드 주의",
      message: "Graves' disease (35/F), methimazole 10mg 복용 중. 환자가 건강 목적으로 다시마 환 복용 문의함. 요오드 섭취로 인한 기능 악화 위험 및 환자 설명용 근거 필요.",
      supplement: "요오드", age: "35", sex: "female", height: "165", weight: "52",
      conditions: "그레이브스병", medications: "메티마졸",
      tsh: "0.01", ft4: "2.8", symptoms: "심계항진, 체중 감소, 안구돌출", treatmentHistory: "메티마졸 유지치료",
      searchFocus: "general"
    },
    {
      id: "D-H2", scope: "mvp", label: "셀레늄 근거",
      message: "Hashimoto thyroiditis (42/F), TPO Ab (+). 피로감 개선 위해 셀레늄 복용 원함. 셀레늄의 임상적 이득 및 장기 복용 시 주의해야 할 독성 관련 최신 근거 요약.",
      supplement: "셀레늄", age: "42", sex: "female", height: "160", weight: "55",
      conditions: "하시모토", medications: "레보티록신",
      tsh: "3.8", ft4: "1.1", symptoms: "피로, 체중 증가, TPOAb 상승", treatmentHistory: "레보티록신 유지치료",
      searchFocus: "general"
    },
    {
      id: "D-H3", scope: "mvp", label: "철분 상호작용",
      message: "Hypothyroidism (38/F), levothyroxine 100mcg 복용 중. 최근 검사에서 IDA 소견으로 철분제(ferrous sulfate) 추가 처방 예정. 씬지로이드 흡수 방해 관련 적절한 투여 간격 및 복약 지도 포인트.",
      supplement: "철분제", age: "38", sex: "female", height: "158", weight: "53",
      conditions: "갑상선기능저하증, 철결핍성빈혈", medications: "레보티록신",
      tsh: "6.2", ft4: "0.8", symptoms: "피로, 두근거림, 창백", treatmentHistory: "레보티록신 유지치료",
      searchFocus: "interaction"
    },
    {
      id: "D-H4", scope: "mvp", label: "아연 병용",
      message: "Levothyroxine 복용 중 (46/M), 피로감 개선 목적으로 아연 보충제 추가 희망. 다가 양이온 제제 병용 시 호르몬제 흡수 저해 여부 및 최소 투약 간격 확인.",
      supplement: "아연", age: "46", sex: "male", height: "174", weight: "72",
      conditions: "갑상선기능저하증", medications: "레보티록신",
      tsh: "4.1", ft4: "1.0", symptoms: "피로, 아연 결핍 의심", treatmentHistory: "레보티록신 유지치료",
      searchFocus: "interaction"
    },
    {
      id: "D-H5", scope: "mvp", label: "비타민D 결핍",
      message: "Hashimoto (45/F), 25(OH)D 18ng/mL 확인됨. 갑상선 자가면역 개선 목적으로 비타민D 투여 시 권고 타겟 용량 및 임상 연구 결과.",
      supplement: "비타민D", age: "45", sex: "female", height: "161", weight: "57",
      conditions: "하시모토", medications: "레보티록신",
      tsh: "4.5", ft4: "0.9", symptoms: "관절통, 우울감, 피로, 비타민D 18ng/mL", treatmentHistory: "레보티록신 유지치료",
      searchFocus: "dosage"
    },
    {
      id: "D-H6", scope: "mvp", label: "마그네슘 간격",
      message: "아침 공복에 levothyroxine 복용 중인 52/F. 수면장애 및 근육 경련으로 밤에 마그네슘 복용 원함. 투약 간격 확보 시 흡수 상호작용 우려 없는지 확인.",
      supplement: "마그네슘", age: "52", sex: "female", height: "159", weight: "60",
      conditions: "갑상선기능저하증", medications: "레보티록신",
      tsh: "3.2", ft4: "1.1", symptoms: "근육 경련, 수면 불편", treatmentHistory: "레보티록신 유지치료",
      searchFocus: "interaction"
    },
    {
      id: "D-H7", scope: "mvp", label: "프로바이오틱스",
      message: "Hypothyroidism 호르몬제 유지 (39/F). 변비 등 위장관 증상 호전 위해 프로바이오틱스 복용 문의. 호르몬제 흡수 및 약효에 미치는 영향 관련 문헌 근거.",
      supplement: "프로바이오틱스", age: "39", sex: "female", height: "166", weight: "61",
      conditions: "갑상선기능저하증", medications: "레보티록신",
      tsh: "2.9", ft4: "1.2", symptoms: "복부 팽만, 변비", treatmentHistory: "레보티록신 유지치료",
      searchFocus: "interaction"
    },
    {
      id: "D-F1", scope: "out", label: "아슈와간다",
      message: "Hashimoto (45/F), 스트레스 완화 위해 Ashwagandha 복용 원함. 갑상선 호르몬 수치에 미치는 영향 및 항진 유발 가능성 관련 안전성 근거 검토.",
      supplement: "아슈와간다", age: "45", sex: "female", height: "160", weight: "57",
      conditions: "하시모토 갑상선염", medications: "레보티록신",
      tsh: "3.5", ft4: "1.0", symptoms: "피로, 스트레스", treatmentHistory: "레보티록신 유지치료",
      searchFocus: "general"
    },
    {
      id: "D-F2", scope: "out", label: "오메가3",
      message: "Hashimoto (50/M), 심혈관 질환 예방 및 자가면역 개선 목적 오메가3 보충 문의. 갑상선 자가면역 관련 직접적인 임상 근거 및 권고사항.",
      supplement: "오메가3", age: "50", sex: "male", height: "172", weight: "68",
      conditions: "하시모토 갑상선염", medications: "레보티록신",
      tsh: "3.2", ft4: "1.1", symptoms: "피로, LDL 상승", treatmentHistory: "레보티록신 유지치료",
      searchFocus: "general"
    },
  ];

  function fillDoctorScenario(id) {
    const c = DOC_SAMPLE_CASES.find(s => s.id === id);
    if (!c) return;
    const set = (elId, val) => { const el = document.getElementById(elId); if (el) el.value = val ?? ""; };
    set("doc-message", c.message);
    set("doc-age", c.age);
    set("doc-sex", c.sex);
    set("doc-height", c.height);
    set("doc-weight", c.weight);
    set("doc-lab-tsh", c.tsh);
    set("doc-lab-ft4", c.ft4);
    const focusEl = document.getElementById("doc-search-focus");
    if (focusEl) focusEl.value = c.searchFocus || "auto";
    // 태그 선택형 필드 채우기
    setTagField(getTagFieldConfig("doc-supplement"), c.supplement);
    setTagField(getTagFieldConfig("doc-conditions"), c.conditions);
    setTagField(getTagFieldConfig("doc-medications"), c.medications);
    setTagField(getTagFieldConfig("doc-treatment-history"), c.treatmentHistory || "");
    // 증상은 예시로 자동 주입하지 않음 — "입력 안 한 증상이 결과에 보임" 혼란 방지.
    // 의사가 직접 입력한 증상만 결과에 "입력된 주요 증상"으로 표시되고,
    // 진단축 전형 증상은 백엔드가 "추가 확인 권장"으로 별도 라벨 노출.
    setTagField(getTagFieldConfig("doc-symptoms-diet"), "");
    updateDocBmi();
  }

  document.querySelectorAll(".doc-sample-btn").forEach(btn => {
    btn.addEventListener("click", () => fillDoctorScenario(btn.dataset.case));
  });

  document.querySelectorAll(".pat-sample-btn").forEach(btn => {
    btn.addEventListener("click", () => fillPatientScenario(btn.dataset.case));
  });

  document.querySelectorAll(".pat-sample-clear").forEach(btn => {
    btn.addEventListener("click", clearPatientScenario);
  });

  const docBtn = document.getElementById("doctor-btn");
  const docOut = document.getElementById("doctor-output");

  docBtn.addEventListener("click", async () => {
    const message = document.getElementById("doc-message").value.trim();
    const supplement = document.getElementById("doc-supplement").value.trim();
    const age = document.getElementById("doc-age").value;
    const sex = document.getElementById("doc-sex").value;
    const height = document.getElementById("doc-height").value;
    const weight = document.getElementById("doc-weight").value;
    const treatmentHistory = document.getElementById("doc-treatment-history").value.trim();

    let conditions = document.getElementById("doc-conditions").value.split(",").map(s => s.trim()).filter(Boolean);
    let medications = document.getElementById("doc-medications").value.split(",").map(s => s.trim()).filter(Boolean);
    const tsh = document.getElementById("doc-lab-tsh").value.trim();
    const ft4 = document.getElementById("doc-lab-ft4").value.trim();
    const symptomsDiet = document.getElementById("doc-symptoms-diet").value.trim();
    const searchFocusEl = document.getElementById("doc-search-focus");
    const searchFocusVal = searchFocusEl ? searchFocusEl.value : "auto";

    if (!supplement) return alert("검토할 영양제 이름을 입력해주세요.");

    const enhancedFlag = document.getElementById("enhanced-search-toggle")?.checked ?? false;
    const progress = startDoctorProgress(docOut, enhancedFlag);
    document.getElementById("doctor-result-toolbar")?.classList.add("initially-hidden");
    hideCaseFeedbackBlock();

    try {
      const focusBody = searchFocusVal !== "auto" ? { focus: searchFocusVal } : {};
      const res = await fetch(`${API_BASE}/doctor/thyroid-consult`, {
        method: "POST",
        headers: getAuthHeaders(),
        body: JSON.stringify({
          supplement,
          message,
          conditions,
          medications,
          treatment_history: treatmentHistory,
          lab_values: {
            TSH: tsh ? parseFloat(tsh) : null,
            freeT4: ft4 ? parseFloat(ft4) : null
          },
          symptoms: symptomsDiet,
          age: age ? parseInt(age) : null,
          sex,
          height: height ? parseFloat(height) : null,
          weight: weight ? parseFloat(weight) : null,
          supplement_attitude: document.getElementById("prof-attitude")?.value || "neutral",
          risk_tolerance: document.getElementById("prof-risk")?.value || "moderate",
          use_pubmed: true,
          enhanced_search: document.getElementById("enhanced-search-toggle")?.checked ?? false,
          ...focusBody
        })
      });
      if (res.status === 401) {
        docOut.innerHTML = renderStateCard(
          "의사 로그인이 필요합니다",
          "의사 계정으로 로그인한 뒤 다시 실행해 주세요.",
          "empty"
        );
        return;
      }
      if (!res.ok) {
        let errDetail = `서버 오류 (HTTP ${res.status})`;
        try { const e = await res.json(); if (e.detail) errDetail = e.detail; } catch (_) { }
        docOut.innerHTML = renderStateCard("분석 오류", errDetail, "error");
        return;
      }
      const data = await res.json();
      docOut.innerHTML = renderDoctorResponse(data);
      document.getElementById("doctor-result-toolbar")?.classList.remove("initially-hidden");

      // 상담 스냅샷 저장 (피드백 폼에 사용)
      lastConsult = {
        consultInput: {
          supplement,
          message,
          conditions,
          medications,
          treatment_history: treatmentHistory,
          lab_values: {
            TSH: tsh ? parseFloat(tsh) : null,
            freeT4: ft4 ? parseFloat(ft4) : null,
          },
          symptoms: symptomsDiet,
          age: age ? parseInt(age) : null,
          sex,
          height: height ? parseFloat(height) : null,
          weight: weight ? parseFloat(weight) : null,
          use_pubmed: true,
          enhanced_search: document.getElementById("enhanced-search-toggle")?.checked ?? false,
        },
        consultMessage: message,
        consultResponse: data,
      };
      showCaseFeedbackForm();
      requestAnimationFrame(() => {
        document.getElementById("case-feedback-container")?.scrollIntoView({ behavior: "smooth", block: "nearest" });
      });
    } catch (e) {
      docOut.innerHTML = renderStateCard(
        "분석에 실패했습니다",
        "입력값, 로그인 상태, 서버 연결을 확인한 뒤 다시 실행해 주세요.",
        "error"
      );
      console.error(e);
    } finally {
      progress.stop();
    }
  });

  // ──────────────────────────────────────────────────────────
  // 피드백 기능
  // ──────────────────────────────────────────────────────────

  // 1번: 상담 직후 케이스 피드백 — 답변 카드 아래 별도 블록
  function hideCaseFeedbackBlock() {
    const container = document.getElementById("case-feedback-container");
    if (!container) return;
    container.classList.add("hidden");
    container.setAttribute("aria-hidden", "true");
    container.innerHTML = "";
  }

  function showCaseFeedbackForm() {
    const container = document.getElementById("case-feedback-container");
    if (!container || !lastConsult) return;
    container.classList.remove("hidden");
    container.setAttribute("aria-hidden", "false");
    container.innerHTML = `
      <div class="case-feedback-block-inner">
        <div class="case-feedback-block-header">
          <h3>이 답변에 대한 피드백</h3>
          <button type="button" id="case-feedback-close-btn" class="secondary-btn mini" aria-label="닫기">닫기</button>
        </div>
        <div class="form-group">
          <label>자유 의견 (자연어로 작성)</label>
          <textarea id="fb-comment" rows="5" placeholder="답변의 적절성, 누락된 근거, 수정이 필요한 부분 등을 자유롭게 작성해 주세요."></textarea>
        </div>
        <div class="form-row">
          <div class="form-group">
            <label style="font-size:0.85rem">전반적 적절성</label>
            <select id="fb-overall">
              <option value="appropriate">적절함</option>
              <option value="needs_revision">일부 수정 필요</option>
              <option value="unsafe">부적절 / 위험</option>
            </select>
          </div>
          <div class="form-group">
            <label style="font-size:0.85rem">PubMed 근거</label>
            <select id="fb-pubmed">
              <option value="ok">적절</option>
              <option value="wrong">오류</option>
              <option value="missing">누락</option>
            </select>
          </div>
          <div class="form-group">
            <label style="font-size:0.85rem">상담 포인트</label>
            <select id="fb-counseling">
              <option value="ok">적절</option>
              <option value="wrong">오류</option>
              <option value="missing">누락</option>
            </select>
          </div>
        </div>
        <button type="button" id="fb-submit-btn" class="primary-btn full-btn">제출</button>
      </div>
    `;
    document.getElementById("case-feedback-close-btn")?.addEventListener("click", hideCaseFeedbackBlock);
    document.getElementById("fb-submit-btn")?.addEventListener("click", submitCaseFeedback);
  }

  async function submitCaseFeedback() {
    if (!lastConsult) return;
    const ratings = {
      overall: document.getElementById("fb-overall").value,
      pubmed: document.getElementById("fb-pubmed").value,
      counseling: document.getElementById("fb-counseling").value,
    };
    const comment = document.getElementById("fb-comment").value.trim();
    try {
      const res = await fetch(`${API_BASE}/feedback/case`, {
        method: "POST",
        headers: getAuthHeaders(),
        body: JSON.stringify({
          consult_input: lastConsult.consultInput,
          consult_message: lastConsult.consultMessage,
          consult_response: lastConsult.consultResponse,
          ratings,
          comment,
        }),
      });
      if (res.ok) {
        alert("피드백이 저장되었습니다. 감사합니다!");
        const container = document.getElementById("case-feedback-container");
        if (container) {
          container.innerHTML = `<p class="case-feedback-done">제출되었습니다. 감사합니다.</p>`;
        }
      } else {
        alert("피드백 저장에 실패했습니다. 의사 로그인 상태를 확인해 주세요.");
      }
    } catch (e) {
      console.error(e);
      alert("피드백 저장 중 오류가 발생했습니다.");
    }
  }

  // 2번: 일반 피드백 전송
  document.getElementById("general-feedback-submit-btn")?.addEventListener("click", async () => {
    const category = document.getElementById("general-feedback-category").value;
    const message = document.getElementById("general-feedback-message").value.trim();
    if (!message) return alert("내용을 입력해주세요.");
    try {
      const res = await fetch(`${API_BASE}/feedback/general`, {
        method: "POST",
        headers: getAuthHeaders(),
        body: JSON.stringify({ category, message }),
      });
      if (res.ok) {
        alert("피드백이 전송되었습니다. 감사합니다!");
        document.getElementById("general-feedback-message").value = "";
      } else {
        alert("전송에 실패했습니다. 의사 로그인 상태를 확인해 주세요.");
      }
    } catch (e) {
      console.error(e);
      alert("전송 중 오류가 발생했습니다.");
    }
  });

  // 3/4번: 내 피드백 탭 전환
  window.switchFeedbackTab = (tab) => {
    currentFeedbackTab = tab;
    document.getElementById("fb-tab-cases").classList.toggle("active-tab", tab === "cases");
    document.getElementById("fb-tab-general").classList.toggle("active-tab", tab === "general");
    loadMyFeedback();
  };

  async function loadMyFeedback() {
    const listEl = document.getElementById("my-feedback-list");
    if (!listEl) return;
    listEl.innerHTML = renderStateCard("불러오는 중", "제출한 피드백 목록을 확인하고 있습니다.", "loading");
    const isAdmin = localStorage.getItem("doctor_id") === "dr_lee";

    try {
      const endpoint = currentFeedbackTab === "cases"
        ? `${API_BASE}/feedback/cases`
        : `${API_BASE}/feedback/general-list`;
      const res = await fetch(endpoint, { headers: getAuthHeaders() });
      if (res.status === 401) {
        listEl.innerHTML = renderStateCard("로그인이 필요합니다", "의사 계정으로 로그인하면 제출한 피드백을 확인할 수 있습니다.", "empty");
        return;
      }
      if (!res.ok) {
        const errBody = await res.json().catch(() => ({}));
        const detail = errBody.detail || res.statusText || res.status;
        listEl.innerHTML = renderStateCard("피드백을 불러오지 못했습니다", `상태 ${res.status}: ${String(detail)}`, "error");
        return;
      }
      const items = await res.json();
      if (!Array.isArray(items)) {
        listEl.innerHTML = renderStateCard("피드백 형식을 확인할 수 없습니다", "서버 응답 형식이 예상과 다릅니다.", "error");
        return;
      }
      if (!items.length) {
        listEl.innerHTML = renderStateCard("등록된 피드백이 없습니다", "상담 결과나 시스템 사용 후 피드백을 남기면 이곳에서 확인할 수 있습니다.", "empty");
        return;
      }
      listEl.innerHTML = items.map(item => renderFeedbackItem(item, isAdmin)).join("");

      // 운영자 회신 버튼 이벤트
      listEl.querySelectorAll(".reply-submit-btn").forEach(btn => {
        btn.addEventListener("click", async () => {
          const id = btn.dataset.id;
          const type = btn.dataset.type;
          const textEl = document.getElementById(`reply-text-${id}`);
          const replyText = textEl?.value?.trim();
          if (!replyText) return alert("답변 내용을 입력해주세요.");
          const url = type === "case"
            ? `${API_BASE}/feedback/cases/${id}/reply`
            : `${API_BASE}/feedback/general/${id}/reply`;
          try {
            const r = await fetch(url, {
              method: "POST",
              headers: getAuthHeaders(),
              body: JSON.stringify({ reply_text: replyText }),
            });
            if (r.ok) {
              alert("답변이 저장되었습니다.");
              loadMyFeedback();
            } else {
              alert("저장에 실패했습니다.");
            }
          } catch (e) {
            console.error(e);
          }
        });
      });

      // 상세 토글
      listEl.querySelectorAll(".fb-toggle-detail").forEach(btn => {
        btn.addEventListener("click", () => {
          const id = btn.dataset.id;
          const detail = document.getElementById(`fb-detail-${id}`);
          if (!detail) return;
          const visible = detail.style.display !== "none";
          detail.style.display = visible ? "none" : "block";
          btn.textContent = visible ? "상세 보기 ▾" : "접기 ▴";
        });
      });
    } catch (e) {
      console.error("loadMyFeedback error:", e);
      const msg = e instanceof Error ? e.message : String(e);
      listEl.innerHTML = renderStateCard("불러오기에 실패했습니다", msg, "error");
    }
  }

  function renderFeedbackItem(item, isAdmin) {
    const isCase = !!item.consult_input;
    const type = isCase ? "case" : "general";
    const replyStatus = item.team_reply?.status || "pending";
    const badge = replyStatus === "replied"
      ? `<span class="fb-badge replied">답변완료</span>`
      : `<span class="fb-badge pending">미응답</span>`;
    const dateStr = item.created_at ? item.created_at.slice(0, 16).replace("T", " ") : "";
    const itemId = escapeHtml(item.id || "");

    // 상세 블록 (케이스)
    let detailHtml = "";
    if (isCase) {
      const inp = item.consult_input || {};
      const inpRows = Object.entries(inp)
        .filter(([, v]) => v !== null && v !== undefined && v !== "" && !(Array.isArray(v) && !v.length))
        .map(([k, v]) => {
          const val = typeof v === "object" ? JSON.stringify(v) : String(v);
          return `<tr><td style="color:var(--text-dim);padding:2px 8px 2px 0;white-space:nowrap">${escapeHtml(k)}</td><td>${escapeHtml(val)}</td></tr>`;
        })
        .join("");
      const resp = item.consult_response || {};
      const fb = item.feedback || {};
      const ratings = fb.ratings || {};
      detailHtml = `
        <div id="fb-detail-${itemId}" style="display:none;margin-top:0.8rem;border-top:1px solid var(--border-color);padding-top:0.8rem">
          <div class="fb-block">
            <div class="fb-block-title">입력값</div>
            <table style="font-size:0.82rem;width:100%"><tbody>${inpRows}</tbody></table>
          </div>
          <div class="fb-block">
            <div class="fb-block-title">자연어 질문</div>
            <p style="font-size:0.9rem">${escapeHtml(item.consult_message || "(없음)")}</p>
          </div>
          <div class="fb-block">
            <div class="fb-block-title">시스템 답변 요약</div>
            <p style="font-size:0.85rem"><strong>결론:</strong> ${escapeHtml(resp.conclusion || "-")}</p>
            <p style="font-size:0.85rem"><strong>판정:</strong> ${escapeHtml(resp.decision || "-")}</p>
            ${resp.evidence_summaries?.length ? `<p style="font-size:0.8rem;color:var(--text-dim)">PubMed ${resp.evidence_summaries.length}건</p>` : ""}
          </div>
          <div class="fb-block">
            <div class="fb-block-title">의사 피드백</div>
            <p style="font-size:0.85rem">전반: ${escapeHtml(ratings.overall || "-")} | PubMed: ${escapeHtml(ratings.pubmed || "-")} | 상담: ${escapeHtml(ratings.counseling || "-")}</p>
            ${fb.comment ? `<p style="font-size:0.85rem;margin-top:0.3rem;color:var(--text-secondary)">${escapeHtml(fb.comment)}</p>` : ""}
          </div>
        </div>
      `;
    } else {
      detailHtml = `
        <div id="fb-detail-${itemId}" style="display:none;margin-top:0.8rem;border-top:1px solid var(--border-color);padding-top:0.8rem">
          <div class="fb-block">
            <div class="fb-block-title">카테고리</div>
            <p style="font-size:0.85rem">${escapeHtml(item.category || "-")}</p>
          </div>
          <div class="fb-block">
            <div class="fb-block-title">내용</div>
            <p style="font-size:0.9rem">${escapeHtml(item.message || "")}</p>
          </div>
        </div>
      `;
    }

    const consultInp = isCase ? (item.consult_input || {}) : {};
    const msgPreview = (item.consult_message || "").slice(0, 60);
    const msgSuffix = (item.consult_message || "").length > 60 ? "…" : "";
    const summaryFixed = isCase
      ? `<span style="color:var(--text-secondary)">${escapeHtml(consultInp.supplement || "영양제 미기재")}</span> — ${escapeHtml(msgPreview || "(질문 없음)")}${msgSuffix}`
      : `<span style="color:var(--text-secondary)">[${escapeHtml(item.category || "기타")}]</span> ${escapeHtml((item.message || "").slice(0, 80))}${(item.message || "").length > 80 ? "…" : ""}`;

    // 답변 영역: 관리자는 작성/조회, 일반 의사는 달린 답변만 조회
    const replyHtml = item.team_reply?.status === "replied" ? `
      <div class="fb-reply-box replied">
        <span class="fb-reply-label">팀 답변</span>
        <p>${escapeHtml(item.team_reply.text || "")}</p>
        <span style="font-size:0.75rem;color:var(--text-dim)">${escapeHtml((item.team_reply.replied_at || "").slice(0, 16).replace("T", " "))}</span>
      </div>` : isAdmin ? `
      <div class="fb-reply-box pending">
        <span class="fb-reply-label">팀 답변 작성</span>
        <textarea id="reply-text-${itemId}" rows="3" placeholder="이 피드백에 대한 답변을 작성하세요..."></textarea>
        <button class="primary-btn mini reply-submit-btn" data-id="${itemId}" data-type="${type}" style="margin-top:0.4rem">답변 저장</button>
      </div>` : "";
    const adminReplyInline = replyHtml ? `
      <div class="fb-admin-reply" id="fb-reply-section-${itemId}">${replyHtml}</div>` : "";

    return `
      <div class="glass-panel feedback-item" style="margin-bottom:0.8rem">
        <div style="display:flex;justify-content:space-between;align-items:flex-start;gap:0.5rem">
          <div style="flex:1;min-width:0">
            <p style="font-size:0.85rem;color:var(--text-dim);margin-bottom:0.3rem">${escapeHtml(dateStr)} · ${escapeHtml(item.reviewer_id || "")}</p>
            <p style="font-size:0.93rem;overflow:hidden;text-overflow:ellipsis">${summaryFixed}</p>
          </div>
          <div style="display:flex;gap:0.4rem;align-items:center;flex-shrink:0">
            ${badge}
            <button class="secondary-btn mini fb-toggle-detail" data-id="${item.id}">상세 보기 ▾</button>
          </div>
        </div>
        ${detailHtml}
        ${adminReplyInline}
      </div>
    `;
  }

  // Analytics Logic
  const analyticsBtn = document.getElementById("analytics-btn");

  const TRANSLATIONS = {
    "iodine": "요오드", "selenium": "셀레늄", "ashwagandha": "아슈와간다", "omega3": "오메가3",
    "vitamin_b12": "비타민 B12", "zinc": "아연", "iron": "철분", "calcium": "칼슘",
    "hypothyroidism": "갑상선기능저하증", "hyperthyroidism": "갑상선기능항진증",
    "graves_disease": "그레이브스병", "hashimoto": "하시모토 갑상선염",
    "thyroid_cancer": "갑상선암", "goiter": "갑상선종", "thyroid_nodule": "갑상선결절",
    "recommend": "도움 가능성 제시", "conditional_consider": "조건부 고려", "avoid": "주의 필요",
    "contraindicated": "피해야 할 상황 보고", "insufficient_evidence": "근거 제한적"
  };

  const tr = (k) => TRANSLATIONS[k] || k;

  const renderDecisionChips = (decisions) =>
    Object.entries(decisions || {})
      .sort((a, b) => b[1] - a[1])
      .map(([d, c]) => `<span class="analytics-chip">${escapeHtml(tr(d))} <b>${c}</b></span>`)
      .join("");

  // 영양제별 분포: { 영양제: { 판정: 건수 } } → 건수 막대 + 판정 분해 칩
  const renderSupplementDistribution = (bySupp) => {
    const rows = Object.entries(bySupp || {}).map(([supp, decisions]) => {
      const total = Object.values(decisions || {}).reduce((a, b) => a + b, 0);
      return { supp, decisions, total };
    });
    if (rows.length === 0) {
      return renderStateCard("데이터 없음", "아직 집계된 의사결정 기록이 없습니다.", "empty");
    }
    const maxTotal = Math.max(...rows.map(r => r.total), 1);
    rows.sort((a, b) => b.total - a.total);
    return `<div class="analytics-bar-list">${rows.map(r => `
      <div class="analytics-row">
        <div class="analytics-row-head">
          <span class="analytics-row-label">${escapeHtml(tr(r.supp))}</span>
          <span class="analytics-row-count">${r.total}건</span>
        </div>
        <div class="analytics-bar"><span style="width:${Math.round(r.total / maxTotal * 100)}%"></span></div>
        <div class="analytics-breakdown">${renderDecisionChips(r.decisions)}</div>
      </div>`).join("")}</div>`;
  };

  // 의사 간 변동성: { "영양제|진단": { total, decisions, variability_score } }
  const renderVariability = (variability) => {
    const rows = Object.entries(variability || {}).map(([key, v]) => {
      const [supp, dx = ""] = key.split("|");
      return { supp, dx, ...v };
    });
    if (rows.length === 0) {
      return renderStateCard("변동성 데이터 없음", "동일 조건에서 서로 다른 판정이 2건 이상 누적되면 이곳에 표시됩니다.", "empty");
    }
    rows.sort((a, b) => (b.variability_score || 0) - (a.variability_score || 0));
    return `<div class="analytics-var-list">${rows.map(r => {
      const label = tr(r.supp) + (r.dx ? ` · ${r.dx}` : "");
      const pct = Math.round((r.variability_score || 0) * 100);
      return `
      <div class="analytics-row">
        <div class="analytics-row-head">
          <span class="analytics-row-label">${escapeHtml(label)}</span>
          <span class="analytics-var-score">변동성 ${pct}%</span>
        </div>
        <div class="analytics-breakdown">${renderDecisionChips(r.decisions)}</div>
        <div class="analytics-row-sub">총 ${r.total || 0}건의 판정 기록</div>
      </div>`;
    }).join("")}</div>`;
  };

  const fetchAnalytics = async () => {
    const suppEl = document.getElementById("stat-supplements");
    const physEl = document.getElementById("stat-physician");
    suppEl.innerHTML = renderStateCard("불러오는 중", "분석 데이터를 집계하고 있습니다.", "loading");
    physEl.innerHTML = renderStateCard("불러오는 중", "분석 데이터를 집계하고 있습니다.", "loading");
    try {
      const res = await fetch(`${API_BASE}/analytics/summary`, {
        headers: getAuthHeaders()
      });
      const data = await res.json();
      document.getElementById("stat-total").textContent = data.total_decisions || 0;
      suppEl.innerHTML = renderSupplementDistribution(data.by_supplement || {});
      physEl.innerHTML = renderVariability(data.variability || {});
    } catch (e) {
      console.error(e);
      const errCard = renderStateCard("불러오지 못했습니다", "로그인 상태와 서버 연결을 확인한 뒤 새로고침해 주세요.", "error");
      suppEl.innerHTML = errCard;
      physEl.innerHTML = errCard;
    }
  };

  analyticsBtn.addEventListener("click", fetchAnalytics);

  // Profile Management Logic
  const saveProfileBtn = document.getElementById("save-profile-btn");

  const loadDoctorProfile = async () => {
    try {
      const res = await fetch(`${AUTH_BASE}/doctor/profile`, {
        headers: getAuthHeaders()
      });
      if (res.status === 401) {
        updateAuthState(false);
        return;
      }
      if (!res.ok) return;
      const data = await res.json();

      // Update badge (name only)
      document.getElementById("badge-specialty").textContent = "의사";
      document.getElementById("badge-name").textContent = data.name || "의사";

      // Update profile form (attitude + risk_tolerance only)
      document.getElementById("prof-attitude").value = data.supplement_attitude || "neutral";
      document.getElementById("prof-risk").value = data.risk_tolerance || "moderate";
    } catch (e) {
      console.error("Profile load failed", e);
    }
  };

  saveProfileBtn.addEventListener("click", async () => {
    const attitude = document.getElementById("prof-attitude").value;
    const risk = document.getElementById("prof-risk").value;

    try {
      const res = await fetch(`${AUTH_BASE}/doctor/profile`, {
        method: "PUT",
        headers: getAuthHeaders(),
        body: JSON.stringify({
          specialty: "general",
          years_experience: 0,
          supplement_attitude: attitude,
          risk_tolerance: risk
        })
      });
      if (res.ok) {
        alert("성향 설정이 저장됐습니다.");
        loadDoctorProfile();
      }
    } catch (e) {
      console.error("Profile update failed", e);
      alert("저장에 실패했습니다.");
    }
  });

  // Login/Logout Listeners
  const loginBtn = document.getElementById('login-btn');
  const logoutBtn = document.getElementById('logout-btn');

  // 의사 데모 로그인 — 검토용 일반 의사 (운영자 dr_lee 아님)
  const demoDoctorLoginBtn = document.getElementById('doctor-demo-login-btn');
  if (demoDoctorLoginBtn) {
    demoDoctorLoginBtn.addEventListener('click', async () => {
      document.getElementById('login-id').value = 'dr_review';
      document.getElementById('login-pw').value = 'demo1234';
      loginBtn.click();
    });
  }

  // 환자 데모 로그인 — 가상 환자 vp-001 (프로필 포함)
  const demoPatientLoginBtn = document.getElementById('patient-demo-login-btn');
  const patientLoginBtn = document.getElementById('patient-login-btn');
  if (demoPatientLoginBtn && patientLoginBtn) {
    demoPatientLoginBtn.addEventListener('click', async () => {
      document.getElementById('patient-login-id').value = 'vp-001';
      document.getElementById('patient-login-pw').value = 'demo1234';
      patientLoginBtn.click();
    });
  }

  // 의사 로그인
  loginBtn.addEventListener('click', async () => {
    const doctor_id = document.getElementById('login-id').value.trim();
    const password = document.getElementById('login-pw').value.trim();
    if (!doctor_id || !password) return alert("ID와 비밀번호를 입력해주세요.");
    try {
      const res = await fetch(`${AUTH_BASE}/doctor/login`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ doctor_id, password })
      });
      const data = await res.json();
      if (res.ok) {
        localStorage.setItem('doctor_token', data.access_token);
        localStorage.setItem('doctor_name', data.name);
        localStorage.setItem('doctor_id', doctor_id);
        updateAuthState(true, data.name, 'doctor');
      } else {
        alert(data.detail || "로그인에 실패했습니다.");
      }
    } catch (e) { console.error(e); alert("로그인 오류가 발생했습니다."); }
  });

  // 환자 로그인
  if (patientLoginBtn) patientLoginBtn.addEventListener('click', async () => {
    const patient_id = document.getElementById('patient-login-id').value.trim();
    const password = document.getElementById('patient-login-pw').value.trim();
    if (!patient_id || !password) return alert("ID와 비밀번호를 입력해주세요.");
    try {
      const res = await fetch(`${AUTH_BASE}/login`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ patient_id, password })
      });
      const data = await res.json();
      if (res.ok) {
        localStorage.setItem('patient_token', data.access_token);
        localStorage.setItem('patient_name', data.name);
        localStorage.setItem('patient_role', 'patient');
        updateAuthState(true, data.name, 'patient');
        // 프로필에서 conditions/medications 세션에 임포트
        loadPatientProfile();
      } else {
        alert(data.detail || "로그인에 실패했습니다.");
      }
    } catch (e) { console.error(e); alert("로그인 오류가 발생했습니다."); }
  });

  // 환자 회원가입
  document.getElementById('patient-register-btn').addEventListener('click', async () => {
    const patient_id = document.getElementById('patient-login-id').value.trim();
    const password = document.getElementById('patient-login-pw').value.trim();
    if (!patient_id || !password) return alert("ID와 비밀번호를 입력해주세요.");
    const name = prompt("이름을 입력하세요:") || patient_id;
    try {
      const res = await fetch(`${AUTH_BASE}/register`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ patient_id, password, name })
      });
      const data = await res.json();
      if (res.ok) {
        localStorage.setItem('patient_token', data.access_token);
        localStorage.setItem('patient_name', data.name);
        localStorage.setItem('patient_role', 'patient');
        updateAuthState(true, data.name, 'patient');
        alert("회원가입이 완료되었습니다. 프로필을 설정해주세요.");
      } else {
        alert(data.detail || "회원가입에 실패했습니다.");
      }
    } catch (e) { console.error(e); alert("회원가입 오류가 발생했습니다."); }
  });

  // 환자 프로필 로드
  const loadPatientProfile = async () => {
    const token = localStorage.getItem('patient_token');
    if (!token) return;
    try {
      const res = await fetch(`${AUTH_BASE}/profile`, { headers: getPatientAuthHeaders() });
      if (!res.ok) return;
      const data = await res.json();
      // 프로필 폼 자동 입력 (프로필 섹션만 — 컨텍스트 패널은 환자가 직접 입력)
      const set = (id, val) => { const el = document.getElementById(id); if (el && val !== undefined && val !== null) el.value = val; };
      set('pat-name', data.name);
      set('pat-age', data.age);
      set('pat-sex', data.sex);
      set('pat-conditions', data.conditions);
      set('pat-medications', data.medications);
      set('pat-supplements', data.current_supplements);
      set('pat-literacy', data.health_literacy);
      set('pat-preference', data.preference_type);
      updatePatientInfoMode();
    } catch (e) { console.error('Patient profile load failed', e); }
  };

  // 환자 프로필 저장
  document.getElementById('save-patient-profile-btn').addEventListener('click', async () => {
    const body = {
      name: document.getElementById('pat-name').value || undefined,
      age: document.getElementById('pat-age').value ? parseInt(document.getElementById('pat-age').value) : undefined,
      sex: document.getElementById('pat-sex').value,
      conditions: document.getElementById('pat-conditions').value,
      medications: document.getElementById('pat-medications').value,
      current_supplements: document.getElementById('pat-supplements').value,
      health_literacy: document.getElementById('pat-literacy').value,
      preference_type: document.getElementById('pat-preference').value,
    };
    try {
      const res = await fetch(`${AUTH_BASE}/profile`, {
        method: "PUT",
        headers: getPatientAuthHeaders(),
        body: JSON.stringify(body)
      });
      if (res.ok) {
        updatePatientInfoMode();
        alert("프로필이 저장되었습니다.");
      } else {
        alert("프로필 저장에 실패했습니다.");
      }
    } catch (e) { console.error(e); }
  });

  logoutBtn.addEventListener('click', () => {
    updateAuthState(false);
    sessionConditions = "";
    sessionMedications = "";
    sessionSupplement = "";
    chatHistory = [];
    location.reload();
  });

  // Initial load
  const savedPatientToken = localStorage.getItem('patient_token');
  const savedPatientName = localStorage.getItem('patient_name');
  const savedToken = localStorage.getItem('doctor_token');
  const savedName = localStorage.getItem('doctor_name');
  if (savedPatientToken) {
    updateAuthState(true, savedPatientName, 'patient');
    loadPatientProfile();
  } else if (savedToken) {
    updateAuthState(true, savedName, 'doctor');
  }
});
