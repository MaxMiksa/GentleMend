"use client";

import { useState, useEffect, useCallback } from "react";
import { useRouter } from "next/navigation";
import {
  getOrCreatePatientId,
  submitAssessment,
  type SymptomInput,
} from "@/lib/api";
import { getEventTracker } from "@/lib/event-tracker";
import { useI18n } from "@/lib/i18n";

const SYMPTOM_KEYS = [
  "nausea", "vomiting", "fatigue", "alopecia", "anorexia",
  "diarrhea", "mucositis", "rash", "neuropathy", "arthralgia",
  "fever", "dyspnea", "hot_flash", "cardiotoxicity",
];

export default function InputPage() {
  const router = useRouter();
  const { t, symptomName, severityLevels } = useI18n();
  const [freeText, setFreeText] = useState("");
  const [medicationInfo, setMedicationInfo] = useState("");
  const [medicalHistory, setMedicalHistory] = useState("");
  const [symptoms, setSymptoms] = useState<SymptomInput[]>([]);
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState("");

  useEffect(() => {
    getEventTracker().trackAssessmentStarted();
  }, []);

  const addSymptom = useCallback((name: string) => {
    setSymptoms((prev) => {
      if (prev.some((s) => s.name === name)) return prev;
      return [...prev, { name, severity: 5 }];
    });
  }, []);

  const removeSymptom = useCallback((name: string) => {
    setSymptoms((prev) => prev.filter((s) => s.name !== name));
  }, []);

  const setSeverity = useCallback((name: string, severity: number) => {
    setSymptoms((prev) =>
      prev.map((s) => (s.name === name ? { ...s, severity } : s)),
    );
  }, []);

  const canSubmit = freeText.trim().length > 0 || symptoms.length > 0 || medicationInfo.trim().length > 0;

  async function handleSubmit() {
    if (!canSubmit || submitting) return;
    setSubmitting(true);
    setError("");
    try {
      const patientId = await getOrCreatePatientId();
      const result = await submitAssessment({
        patient_id: patientId,
        symptoms,
        free_text: freeText,
        medication_info: medicationInfo,
        medical_history: medicalHistory,
      });
      getEventTracker().trackAssessmentSubmitted(result.id, {
        inputLength: freeText.length,
        symptomCount: symptoms.length,
      });
      router.push(`/result/${result.id}`);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Submit failed");
      setSubmitting(false);
    }
  }

  return (
    <div className="max-w-3xl mx-auto px-6 py-10">
      <div className="mb-10">
        <h1 className="font-serif text-3xl font-bold text-foreground mb-3">
          {t("input.title")}
        </h1>
        <p className="text-muted text-lg leading-relaxed">{t("input.subtitle")}</p>
      </div>

      {/* 用药与手术 */}
      <section className="mb-8">
        <label htmlFor="medication" className="block text-sm font-medium text-foreground mb-2">
          {t("input.medicationLabel")}
        </label>
        <textarea
          id="medication"
          value={medicationInfo}
          onChange={(e) => setMedicationInfo(e.target.value)}
          placeholder={t("input.medicationPlaceholder")}
          rows={3}
          className="w-full rounded-xl border border-border bg-card px-4 py-3 text-base text-foreground placeholder:text-muted/60 focus:outline-none focus:ring-2 focus:ring-teal/30 focus:border-teal transition-shadow resize-y"
        />
        <p className="mt-1.5 text-xs text-muted">{t("input.medicationHint")}</p>
      </section>

      {/* 既往病史 */}
      <section className="mb-8">
        <label htmlFor="history" className="block text-sm font-medium text-foreground mb-2">
          {t("input.historyLabel")}
        </label>
        <textarea
          id="history"
          value={medicalHistory}
          onChange={(e) => setMedicalHistory(e.target.value)}
          placeholder={t("input.historyPlaceholder")}
          rows={3}
          className="w-full rounded-xl border border-border bg-card px-4 py-3 text-base text-foreground placeholder:text-muted/60 focus:outline-none focus:ring-2 focus:ring-teal/30 focus:border-teal transition-shadow resize-y"
        />
        <p className="mt-1.5 text-xs text-muted">{t("input.historyHint")}</p>
      </section>

      {/* 症状描述 */}
      <section className="mb-8">
        <label htmlFor="free-text" className="block text-sm font-medium text-foreground mb-2">
          {t("input.textLabel")}
        </label>
        <textarea
          id="free-text"
          value={freeText}
          onChange={(e) => setFreeText(e.target.value)}
          placeholder={t("input.textPlaceholder")}
          rows={5}
          className="w-full rounded-xl border border-border bg-card px-4 py-3 text-base text-foreground placeholder:text-muted/60 focus:outline-none focus:ring-2 focus:ring-teal/30 focus:border-teal transition-shadow resize-y"
        />
        <p className="mt-1.5 text-xs text-muted">{t("input.textHint")}</p>
      </section>

      <section className="mb-8">
        <h2 className="text-sm font-medium text-foreground mb-3">{t("input.symptomsTitle")}</h2>
        <div className="flex flex-wrap gap-2">
          {SYMPTOM_KEYS.map((key) => {
            const selected = symptoms.some((s) => s.name === key);
            return (
              <button
                key={key}
                type="button"
                onClick={() => (selected ? removeSymptom(key) : addSymptom(key))}
                className={`px-3.5 py-1.5 rounded-full text-sm font-medium border transition-all ${
                  selected
                    ? "bg-teal text-white border-teal shadow-sm"
                    : "bg-card text-foreground border-border hover:border-teal/40 hover:bg-teal-light"
                }`}
              >
                {selected && <span className="mr-1">✓</span>}
                {symptomName(key)}
              </button>
            );
          })}
        </div>
      </section>

      {symptoms.length > 0 && (
        <section className="mb-8">
          <h2 className="text-sm font-medium text-foreground mb-3">{t("input.severityTitle")}</h2>
          <div className="space-y-4">
            {symptoms.map((s) => {
              const levels = severityLevels(s.name);
              // severity mapping: button 0→2, 1→5, 2→8
              const severityMap = [2, 5, 8];
              const colorMap = ["text-risk-low border-risk-low-border bg-risk-low-bg", "text-risk-medium border-risk-medium-border bg-risk-medium-bg", "text-risk-high border-risk-high-border bg-risk-high-bg"];
              const inactiveClass = "border-border text-foreground/70 bg-card hover:bg-border/20";
              return (
                <div key={s.name} className="rounded-xl border border-border bg-card p-4">
                  <p className="text-sm font-medium text-foreground mb-3">{symptomName(s.name)}</p>
                  <div className="flex flex-col gap-2">
                    {levels.map((label, i) => {
                      const active = s.severity === severityMap[i];
                      return (
                        <button
                          key={i}
                          type="button"
                          onClick={() => setSeverity(s.name, severityMap[i])}
                          className={`w-full text-left px-4 py-2.5 rounded-lg text-sm border transition-all ${
                            active ? colorMap[i] + " font-medium" : inactiveClass
                          }`}
                        >
                          {label}
                        </button>
                      );
                    })}
                  </div>
                </div>
              );
            })}
          </div>
        </section>
      )}

      {error && (
        <div className="mb-6 p-4 rounded-xl bg-risk-high-bg border border-risk-high-border text-risk-high text-sm">
          {error}
        </div>
      )}

      <button
        type="button" onClick={handleSubmit} disabled={!canSubmit || submitting}
        className="w-full py-3.5 rounded-xl text-base font-semibold transition-all bg-teal text-white hover:bg-teal-hover disabled:opacity-40 disabled:cursor-not-allowed shadow-sm hover:shadow-md"
      >
        {submitting ? (
          <span className="inline-flex items-center gap-2">
            <span className="w-4 h-4 border-2 border-white/30 border-t-white rounded-full animate-spin" />
            {t("input.submitting")}
          </span>
        ) : t("input.submit")}
      </button>

      <p className="mt-4 text-xs text-muted text-center">{t("app.disclaimer")}</p>
    </div>
  );
}
