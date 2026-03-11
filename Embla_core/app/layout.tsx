import type { Metadata } from "next";

import "@/styles/globals.css";

import { getRequestLocale } from "@/lib/request-locale";
import { createTranslator } from "@/lib/i18n";

export async function generateMetadata(): Promise<Metadata> {
  const locale = await getRequestLocale();
  const t = createTranslator(locale);
  return {
    title: t("common.meta.title"),
    description: t("common.meta.description")
  };
}

export default async function RootLayout({ children }: { children: React.ReactNode }) {
  const locale = await getRequestLocale();

  return (
    <html lang={locale}>
      <body>{children}</body>
    </html>
  );
}
