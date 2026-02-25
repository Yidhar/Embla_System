import { SettingsConsole } from "@/components/settings/settings-console";
import { resolveLangFromSearchParams } from "@/lib/i18n";

export const dynamic = "force-dynamic";

type SettingsPageProps = {
  searchParams?: Promise<Record<string, string | string[] | undefined>>;
};

export default async function SettingsPage({ searchParams }: SettingsPageProps) {
  const lang = await resolveLangFromSearchParams(searchParams);
  return <SettingsConsole lang={lang} />;
}
