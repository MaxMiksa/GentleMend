"use client";

import { useState, useEffect, useRef } from "react";
import { useParams } from "next/navigation";
import Link from "next/link";
import {
  getAssessment,
  submitContactRequest,
  submitFeedback,
  type AssessmentResponse,
} from "@/lib/api";
import { getEventTracker } from "@/lib/event-tracker";
import { RiskBadge, type RiskLevel } from "@/app/components/risk-badge";
import { useI18n } from "@/lib/i18n";

const riskStyles: Record<string, { color: string; bgClass: string; borderClass: string }> = {
  high:   { color: "text-risk-high",   bgClass: "bg-risk-high-bg",   borderClass: "border-risk-high-border" },
  medium: { color: "text-risk-medium", bgClass: "bg-risk-medium-bg", borderClass: "border-risk-medium-border" },
  low:    { color: "text-risk-low",    bgClass: "bg-risk-low-bg",    borderClass: "border-risk-low-border" },
};

export default function ResultPage() {
  const params = useParams();
  const id = params.id as string;
  const { t, symptomName, locale } = useI18n();
  const [data, setData] = useState<AssessmentResponse | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [contacted, setContacted] = useState(false);
  const [feedbackSent, setFeedbackSent] = useState(false);
  const enterTime = useRef(Date.now());

  useEffect(() => {
    const start = performance.now();
    getAssessment(id)
      .then((res) => {
        setData(res);
        getEventTracker().trackResultViewed(id, {
          riskLevel: res.risk_level ?? "unknown",
          loadTimeMs: Math.round(performance.now() - start),
        });
      })
      .catch((e) => setError(e instanceof Error ? e.message : "Load failed"))
      .finally(() => setLoading(false));
    return () => {
      getEventTracker().trackAssessmentClosed(id, {
        durationSec: Math.round((Date.now() - enterTime.current) / 1000),
        completed: true,
      });
    };
  }, [id]);

  async function handleContact() {
    if (!data) return;
    setContacted(true);
    getEventTracker().trackContactTeamClicked(id, { urgency: data.risk_level ?? "unknown" });
    try { await submitContactRequest(id); } catch {}
  }

  if (loading) {
    return (
      <div className="max-w-3xl mx-auto px-6 py-20 text-center">
        <div className="w-8 h-8 border-3 border-teal/20 border-t-teal rounded-full animate-spin mx-auto mb-4" />
        <p className="text-muted">{t("result.loading")}</p>
      </div>
    );
  }

  if (error || !data) {
    return (
      <div className="max-w-3xl mx-auto px-6 py-20 text-center">
        <p className="text-risk-high mb-4">{error || t("result.notFound")}</p>
        <Link href="/" className="text-teal hover:underline">{t("result.backHome")}</Link>
      </div>
    );
  }

  const risk = (data.risk_level ?? "low") as RiskLevel;
  const s = riskStyles[risk] ?? riskStyles.low;
  const yesNo = (v: boolean) => v ? t("result.yes") : t("result.no");

  return (
    <div className="max-w-3xl mx-auto px-6 py-10">
      {/* Risk hero */}
      <section className={`rounded-2xl border-2 ${s.borderClass} ${s.bgClass} p-8 mb-8`}>
        <div className="flex items-start justify-between mb-4">
          <div>
            <p className="text-sm text-muted mb-2">{t("result.title")}</p>
            <RiskBadge level={risk} size="lg" />
          </div>
          {data.overall_risk_score != null && (
            <div className="text-right">
              <p className="text-xs text-muted mb-1">{t("result.riskScore")}</p>
              <p className={`text-3xl font-bold font-serif ${s.color}`}>
                {Math.round(data.overall_risk_score * 100)}
              </p>
            </div>
          )}
        </div>
        <p className={`text-lg font-medium ${s.color}`}>{t(`risk.msg${risk.charAt(0).toUpperCase() + risk.slice(1)}`)}</p>
      </section>

      {/* AI structured explanation */}
      {data.patient_explanation && (() => {
        const lines = data.patient_explanation.split("\n").filter(Boolean);
        // Group lines into blocks: a header (【...】) followed by its detail lines
        const blocks: { type: string; header?: string; lines: string[] }[] = [];
        for (const raw of lines) {
          const line = raw.trim();
          if (line.startsWith("【主诉概要】")) {
            blocks.push({ type: "summary", header: line.slice(6), lines: [] });
          } else if (line.startsWith("【需要重视】")) {
            blocks.push({ type: "high", header: line.slice(6), lines: [] });
          } else if (line.startsWith("【无需过虑】")) {
            blocks.push({ type: "low", header: line.slice(6), lines: [] });
          } else if (blocks.length > 0) {
            blocks[blocks.length - 1].lines.push(line);
          } else {
            blocks.push({ type: "text", lines: [line] });
          }
        }

        return (
          <section className="mb-8 space-y-3">
            {blocks.map((block, bi) => {
              if (block.type === "summary") {
                return (
                  <div key={bi} className="p-4 rounded-xl bg-card border border-border">
                    <p className="text-xs font-medium text-teal mb-1.5">【主诉概要】</p>
                    <p className="text-base text-foreground leading-relaxed">{block.header}</p>
                  </div>
                );
              }
              const isHigh = block.type === "high";
              const borderColor = isHigh ? "border-risk-high-border" : "border-risk-low-border";
              const bgHeader = isHigh ? "bg-risk-high-bg" : "bg-risk-low-bg";
              const textColor = isHigh ? "text-risk-high" : "text-risk-low";
              return (
                <div key={bi} className={`rounded-xl border ${borderColor} overflow-hidden`}>
                  <div className={`px-4 pt-3 pb-2 ${bgHeader}`}>
                    <p className={`text-sm font-semibold ${textColor}`}>
                      {isHigh ? "【需要重视】" : "【无需过虑】"}{block.header}
                    </p>
                  </div>
                  {block.lines.length > 0 && (
                    <div className="px-4 py-3 bg-card space-y-1.5">
                      {block.lines.map((ln, li) => {
                        const colonIdx = ln.indexOf("：");
                        if (colonIdx > 0 && colonIdx < 6) {
                          const label = ln.slice(0, colonIdx);
                          const content = ln.slice(colonIdx + 1);
                          return (
                            <p key={li} className="text-sm text-foreground/80">
                              <span className="font-medium text-foreground">{label}：</span>{content}
                            </p>
                          );
                        }
                        return <p key={li} className="text-sm text-foreground/70 leading-relaxed">{ln}</p>;
                      })}
                    </div>
                  )}
                </div>
              );
            })}
          </section>
        );
      })()}

      {/* Contact — high risk */}
      {risk === "high" && (
        <section className="mb-8 p-6 rounded-2xl bg-risk-high-bg border-2 border-risk-high">
          <div className="flex items-center gap-3 mb-3">
            <span className="text-2xl" aria-hidden="true">📞</span>
            <h2 className="font-serif text-xl font-bold text-risk-high">{t("result.contactTitle")}</h2>
          </div>
          <p className="text-sm text-foreground/80 mb-4">{t("result.contactDesc")}</p>
          <button type="button" onClick={handleContact} disabled={contacted}
            className="w-full py-3.5 rounded-xl text-base font-bold bg-risk-high text-white hover:opacity-90 disabled:opacity-60 transition-opacity shadow-md">
            {contacted ? t("result.contactSent") : t("result.contactBtn")}
          </button>
        </section>
      )}

      {/* Contact — medium risk */}
      {risk === "medium" && (
        <section className="mb-8 flex items-center justify-between p-5 rounded-xl bg-risk-medium-bg border border-risk-medium-border">
          <p className="text-sm text-foreground/80">{t("result.contactMedium")}</p>
          <button type="button" onClick={handleContact} disabled={contacted}
            className="px-5 py-2 rounded-lg text-sm font-semibold bg-risk-medium text-white hover:opacity-90 disabled:opacity-60 transition-opacity shrink-0">
            {contacted ? t("result.contactMediumSent") : t("result.contactMediumBtn")}
          </button>
        </section>
      )}

      {/* Evidences */}
      {data.evidences.length > 0 && (
        <section className="mb-8">
          <h2 className="font-serif text-xl font-bold text-foreground mb-4">{t("result.evidencesTitle")}</h2>
          <div className="bg-card rounded-xl border border-border divide-y divide-border">
            {data.evidences.map((ev, i) => (
              <div key={i} className="p-4">
                <div className="flex items-center justify-between mb-1.5">
                  <code className="text-xs font-mono bg-background px-2 py-0.5 rounded text-teal">{ev.rule_id}</code>
                  <span className="text-xs text-muted">v{ev.rule_version} · {t("result.confidence")} {Math.round(ev.confidence * 100)}%</span>
                </div>
                {ev.evidence_text && <p className="text-sm text-foreground/80">{ev.evidence_text}</p>}
              </div>
            ))}
          </div>
        </section>
      )}

      {/* CTCAE grades */}
      {data.ctcae_grades && Object.keys(data.ctcae_grades).length > 0 && (
        <section className="mb-8">
          <h2 className="font-serif text-xl font-bold text-foreground mb-4">{t("result.ctcaeTitle")}</h2>
          <div className="grid grid-cols-2 gap-3 sm:grid-cols-3">
            {Object.entries(data.ctcae_grades).map(([sym, grade]) => (
              <div key={sym} className="p-3 rounded-xl bg-card border border-border text-center">
                <p className="text-sm text-muted">{symptomName(sym)}</p>
                <p className="text-2xl font-bold font-serif text-foreground mt-1">Grade {grade}</p>
              </div>
            ))}
          </div>
        </section>
      )}

      {/* Metadata */}
      <section className="mb-8 p-4 rounded-xl bg-background border border-border">
        <div className="flex flex-wrap gap-x-6 gap-y-2 text-xs text-muted">
          <span>{t("result.assessTime")}：{new Date(data.created_at).toLocaleString(locale === "zh" ? "zh-CN" : "en-US")}</span>
          {data.rule_engine_version && <span>{t("result.ruleEngine")}：v{data.rule_engine_version}</span>}
          <span>{t("result.aiExtract")}：{yesNo(data.ai_extraction_used)}</span>
          <span>{t("result.aiEnhance")}：{yesNo(data.ai_enhancement_used)}</span>
        </div>
      </section>

      {/* Feedback */}
      {!feedbackSent ? (
        <section className="mb-8 p-5 rounded-xl bg-card border border-border">
          <p className="text-sm font-medium text-foreground mb-3">{t("feedback.question")}</p>
          <div className="flex gap-3">
            <button type="button" onClick={async () => { await submitFeedback(id, 5, true); setFeedbackSent(true); }}
              className="flex-1 py-2.5 rounded-lg text-sm font-medium border border-risk-low-border text-risk-low hover:bg-risk-low-bg transition-colors">
              {t("feedback.helpful")}
            </button>
            <button type="button" onClick={async () => { await submitFeedback(id, 2, false); setFeedbackSent(true); }}
              className="flex-1 py-2.5 rounded-lg text-sm font-medium border border-border text-muted hover:bg-border/30 transition-colors">
              {t("feedback.notHelpful")}
            </button>
          </div>
        </section>
      ) : (
        <section className="mb-8 p-4 rounded-xl bg-teal-light text-teal text-sm text-center">
          {t("feedback.thanks")}
        </section>
      )}

      {/* Actions */}
      <div className="flex gap-3">
        <Link href="/" className="flex-1 py-3 rounded-xl text-center text-base font-semibold bg-teal text-white hover:bg-teal-hover transition-colors">
          {t("result.newAssess")}
        </Link>
        <Link href="/history" className="flex-1 py-3 rounded-xl text-center text-base font-semibold border border-border text-foreground hover:bg-border/30 transition-colors">
          {t("result.viewHistory")}
        </Link>
      </div>
    </div>
  );
}
