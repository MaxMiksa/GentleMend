const BASE = "/api/v1";

export interface SymptomInput {
  name: string;
  severity: number;
  frequency?: string;
  body_region?: string;
}

export interface AssessmentRequest {
  patient_id: string;
  symptoms: SymptomInput[];
  free_text: string;
  medication_info: string;
  medical_history: string;
}

export interface AdviceItem {
  content: string;
  advice_type: string;
  priority: number;
  source_type: string;
}

export interface EvidenceItem {
  rule_id: string;
  rule_version: string;
  confidence: number;
  evidence_text: string | null;
}

export interface AssessmentResponse {
  id: string;
  patient_id: string;
  status: string;
  risk_level: string | null;
  overall_risk_score: number | null;
  free_text_input: string;
  symptoms_structured: Array<{ name: string; severity: number }> | null;
  ctcae_grades: Record<string, number> | null;
  advices: AdviceItem[];
  evidences: EvidenceItem[];
  patient_explanation: string | null;
  grading_rationale: string | null;
  rule_engine_version: string | null;
  ai_extraction_used: boolean;
  ai_enhancement_used: boolean;
  created_at: string;
}

export interface AssessmentListItem {
  id: string;
  risk_level: string | null;
  status: string;
  free_text_input: string;
  symptom_count: number;
  created_at: string;
}

export interface PaginatedResponse {
  items: AssessmentListItem[];
  total: number;
  page: number;
  page_size: number;
}

// MVP 固定患者 ID — 首次调用时自动创建
const PATIENT_STORAGE_KEY = "gentlemend_patient_id";

export async function getOrCreatePatientId(): Promise<string> {
  if (typeof window === "undefined") return "";
  const stored = localStorage.getItem(PATIENT_STORAGE_KEY);
  if (stored) return stored;

  const res = await fetch(`${BASE}/patients/`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      name: "默认用户",
      age: 50,
      gender: "female",
      diagnosis: "乳腺癌",
      treatment_regimen: "化疗方案",
    }),
  });
  const data = await res.json();
  localStorage.setItem(PATIENT_STORAGE_KEY, data.id);
  return data.id;
}

export async function submitAssessment(
  req: AssessmentRequest,
): Promise<AssessmentResponse> {
  const res = await fetch(`${BASE}/assessments/`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(req),
  });
  if (!res.ok) throw new Error(`评估提交失败: ${res.status}`);
  return res.json();
}

export async function getAssessment(id: string): Promise<AssessmentResponse> {
  const res = await fetch(`${BASE}/assessments/${id}`);
  if (!res.ok) throw new Error(`获取评估失败: ${res.status}`);
  return res.json();
}

export async function listAssessments(
  page = 1,
  pageSize = 20,
  riskLevel?: string,
): Promise<PaginatedResponse> {
  const params = new URLSearchParams({
    page: String(page),
    page_size: String(pageSize),
  });
  if (riskLevel) params.set("risk_level", riskLevel);
  const res = await fetch(`${BASE}/assessments/?${params}`);
  if (!res.ok) throw new Error(`获取历史失败: ${res.status}`);
  return res.json();
}

export async function submitContactRequest(
  assessmentId: string,
): Promise<void> {
  await fetch(`${BASE}/contact-requests/`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ assessment_id: assessmentId }),
  });
}

export async function submitFeedback(
  assessmentId: string,
  rating: number,
  isHelpful: boolean,
  comment?: string,
): Promise<boolean> {
  const res = await fetch(`${BASE}/assessments/${assessmentId}/feedback`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ rating, is_helpful: isHelpful, comment }),
  });
  return res.ok || res.status === 409; // 409 = already submitted
}
