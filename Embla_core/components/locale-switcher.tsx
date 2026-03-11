"use client";

import { useEffect, useState } from "react";
import { Globe2 } from "lucide-react";

import { AppLocale, LOCALE_COOKIE_NAME, getLocaleOptions, translate } from "@/lib/i18n";
import { cx } from "@/lib/format";

export function LocaleSwitcher({ locale, className }: { locale: AppLocale; className?: string }) {
  const [selectedLocale, setSelectedLocale] = useState<AppLocale>(locale);
  const [switchingTo, setSwitchingTo] = useState<AppLocale | null>(null);
  const options = getLocaleOptions(selectedLocale);

  useEffect(() => {
    setSelectedLocale(locale);
    setSwitchingTo(null);
  }, [locale]);

  function handleSwitch(nextLocale: AppLocale) {
    if (nextLocale === selectedLocale || switchingTo !== null) {
      return;
    }

    setSelectedLocale(nextLocale);
    setSwitchingTo(nextLocale);
    document.cookie = `${LOCALE_COOKIE_NAME}=${nextLocale}; Path=/; Max-Age=31536000; SameSite=Lax`;
    document.documentElement.lang = nextLocale;
    window.location.reload();
  }

  return (
    <div className={cx("flex w-full flex-col gap-2 rounded-[24px] border border-white/70 bg-white/75 px-3 py-3 text-xs font-semibold text-slate-600 shadow-[inset_0_1px_0_rgba(255,255,255,0.75)]", className)}>
      <div className="inline-flex items-center gap-2">
        <Globe2 className="h-3.5 w-3.5 shrink-0" />
        <span>{translate(selectedLocale, "common.locale.label")}</span>
      </div>
      <div
        className="grid grid-cols-2 items-center gap-1 rounded-full border border-white/80 bg-white p-1"
        role="group"
        aria-label={translate(selectedLocale, "common.locale.label")}
      >
        {options.map((option) => {
          const active = option.value === selectedLocale;
          return (
            <button
              key={option.value}
              type="button"
              onClick={() => handleSwitch(option.value)}
              disabled={switchingTo !== null || active}
              aria-pressed={active}
              className={cx(
                "min-w-0 rounded-full px-2 py-1.5 text-center text-xs transition duration-150",
                active ? "bg-[#1C1C1E] text-white" : "bg-transparent text-slate-700 hover:bg-slate-100",
                "disabled:cursor-default disabled:opacity-100"
              )}
            >
              {option.label}
            </button>
          );
        })}
      </div>
    </div>
  );
}
