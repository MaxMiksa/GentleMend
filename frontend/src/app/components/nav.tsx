"use client";

import Link from "next/link";
import Image from "next/image";
import { usePathname } from "next/navigation";
import { useI18n, type Locale } from "@/lib/i18n";

export function Nav() {
  const pathname = usePathname();
  const { locale, setLocale, t } = useI18n();

  const links = [
    { href: "/", label: t("nav.assess") },
    { href: "/history", label: t("nav.history") },
  ];

  return (
    <header className="border-b border-border bg-card/80 backdrop-blur-sm sticky top-0 z-50">
      <div className="max-w-3xl mx-auto px-6 h-16 flex items-center justify-between">
        <Link href="/" className="flex items-center gap-2.5 group">
          <Image src="/logo.png" alt="Logo" width={32} height={32} className="w-8 h-8 rounded-lg" />
          <span className="font-serif font-semibold text-lg tracking-wide text-foreground">
            {t("nav.brand")}
          </span>
        </Link>
        <div className="flex items-center gap-3">
          <nav className="flex gap-1">
            {links.map(({ href, label }) => {
              const active = href === "/" ? pathname === "/" : pathname.startsWith(href);
              return (
                <Link
                  key={href}
                  href={href}
                  className={`px-4 py-2 rounded-lg text-sm font-medium transition-colors ${
                    active
                      ? "bg-teal-light text-teal"
                      : "text-muted hover:text-foreground hover:bg-border/50"
                  }`}
                >
                  {label}
                </Link>
              );
            })}
          </nav>
          <button
            type="button"
            onClick={() => setLocale(locale === "zh" ? "en" : "zh")}
            className="px-2.5 py-1.5 rounded-lg text-xs font-medium border border-border text-muted hover:text-foreground hover:bg-border/30 transition-colors"
            aria-label="Switch language"
          >
            {locale === "zh" ? "EN" : "中"}
          </button>
        </div>
      </div>
    </header>
  );
}
