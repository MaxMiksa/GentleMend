"use client";

import { useI18n } from "@/lib/i18n";

export function Footer() {
  const { t } = useI18n();
  return (
    <footer className="border-t border-border py-6 text-center text-sm text-muted">
      <p>{t("app.footer")}</p>
    </footer>
  );
}
