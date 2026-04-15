"use client";

import { useState, useEffect } from "react";
import Link from "next/link";
import { listAssessments, type AssessmentListItem } from "@/lib/api";
import { RiskBadge, type RiskLevel } from "@/app/components/risk-badge";
import { useI18n } from "@/lib/i18n";

export default function HistoryPage() {
  const { t, locale } = useI18n();
  const [items, setItems] = useState<AssessmentListItem[]>([]);
  const [total, setTotal] = useState(0);
  const [page, setPage] = useState(1);
  const [filter, setFilter] = useState("");
  const [loading, setLoading] = useState(true);

  const filters = [
    { value: "", label: t("history.filterAll") },
    { value: "high", label: t("history.filterHigh") },
    { value: "medium", label: t("history.filterMedium") },
    { value: "low", label: t("history.filterLow") },
  ];

  useEffect(() => {
    setLoading(true);
    listAssessments(page, 20, filter || undefined)
      .then((res) => { setItems(res.items); setTotal(res.total); })
      .catch(() => setItems([]))
      .finally(() => setLoading(false));
  }, [page, filter]);

  const totalPages = Math.ceil(total / 20);

  return (
    <div className="max-w-3xl mx-auto px-6 py-10">
      <div className="mb-8">
        <h1 className="font-serif text-3xl font-bold text-foreground mb-3">{t("history.title")}</h1>
        <p className="text-muted">{t("history.total", { count: total })}</p>
      </div>

      <div className="flex gap-2 mb-6">
        {filters.map((f) => (
          <button key={f.value} type="button"
            onClick={() => { setFilter(f.value); setPage(1); }}
            className={`px-4 py-2 rounded-lg text-sm font-medium transition-colors ${
              filter === f.value ? "bg-teal text-white" : "bg-card border border-border text-muted hover:text-foreground hover:border-teal/40"
            }`}>{f.label}</button>
        ))}
      </div>

      {loading ? (
        <div className="py-20 text-center">
          <div className="w-8 h-8 border-3 border-teal/20 border-t-teal rounded-full animate-spin mx-auto mb-4" />
          <p className="text-muted">{t("history.loading")}</p>
        </div>
      ) : items.length === 0 ? (
        <div className="py-20 text-center">
          <p className="text-muted mb-4">{t("history.empty")}</p>
          <Link href="/" className="text-teal hover:underline">{t("history.startFirst")}</Link>
        </div>
      ) : (
        <div className="space-y-3">
          {items.map((item) => (
            <Link key={item.id} href={`/result/${item.id}`}
              className="block p-5 rounded-xl bg-card border border-border hover:border-teal/40 hover:shadow-sm transition-all group">
              <div className="flex items-center justify-between mb-2">
                <RiskBadge level={(item.risk_level ?? "low") as RiskLevel} size="sm" />
                <span className="text-xs text-muted">
                  {new Date(item.created_at).toLocaleString(locale === "zh" ? "zh-CN" : "en-US")}
                </span>
              </div>
              <p className="text-sm text-foreground line-clamp-2 group-hover:text-teal transition-colors">
                {item.free_text_input || t("history.symptoms", { count: item.symptom_count })}
              </p>
            </Link>
          ))}
        </div>
      )}

      {totalPages > 1 && (
        <div className="flex items-center justify-center gap-2 mt-8">
          <button type="button" onClick={() => setPage((p) => Math.max(1, p - 1))} disabled={page <= 1}
            className="px-4 py-2 rounded-lg text-sm border border-border disabled:opacity-30 hover:bg-border/30 transition-colors">
            {t("history.prevPage")}
          </button>
          <span className="text-sm text-muted px-3">{page} / {totalPages}</span>
          <button type="button" onClick={() => setPage((p) => Math.min(totalPages, p + 1))} disabled={page >= totalPages}
            className="px-4 py-2 rounded-lg text-sm border border-border disabled:opacity-30 hover:bg-border/30 transition-colors">
            {t("history.nextPage")}
          </button>
        </div>
      )}
    </div>
  );
}
