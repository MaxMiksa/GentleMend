"use client";

import { useI18n } from "@/lib/i18n";

export type RiskLevel = "low" | "medium" | "high";

const styles: Record<RiskLevel, { bg: string; text: string; border: string; icon: string }> = {
  low:    { bg: "bg-risk-low-bg",    text: "text-risk-low",    border: "border-risk-low-border",    icon: "✓" },
  medium: { bg: "bg-risk-medium-bg", text: "text-risk-medium", border: "border-risk-medium-border", icon: "⚠" },
  high:   { bg: "bg-risk-high-bg",   text: "text-risk-high",   border: "border-risk-high-border",   icon: "⚡" },
};

export function RiskBadge({
  level,
  size = "md",
}: {
  level: RiskLevel;
  size?: "sm" | "md" | "lg";
}) {
  const { t } = useI18n();
  const c = styles[level] ?? styles.low;
  const label = t(`risk.${level}`);
  const sizeClass = {
    sm: "px-2.5 py-0.5 text-xs",
    md: "px-3 py-1 text-sm",
    lg: "px-4 py-1.5 text-base",
  }[size];

  return (
    <span
      className={`inline-flex items-center gap-1.5 rounded-full border font-medium ${c.bg} ${c.text} ${c.border} ${sizeClass}`}
      role="status"
      aria-label={label}
    >
      <span aria-hidden="true">{c.icon}</span>
      {label}
    </span>
  );
}
