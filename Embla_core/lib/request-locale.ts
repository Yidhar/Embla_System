import "server-only";

import { cookies, headers } from "next/headers";

import {
  AppLocale,
  LOCALE_COOKIE_NAME,
  createTranslator,
  matchLocaleFromAcceptLanguage,
  normalizeLocale
} from "@/lib/i18n";

export async function getRequestLocale(): Promise<AppLocale> {
  const cookieStore = await cookies();
  const cookieValue = cookieStore.get(LOCALE_COOKIE_NAME)?.value;
  if (cookieValue) {
    return normalizeLocale(cookieValue);
  }

  const headerStore = await headers();
  return matchLocaleFromAcceptLanguage(headerStore.get("accept-language"));
}

export async function getServerI18n() {
  const locale = await getRequestLocale();
  return {
    locale,
    t: createTranslator(locale)
  };
}
