import { DashboardShell } from "@/components/dashboard-shell";
import { getRequestLocale } from "@/lib/request-locale";

export default async function DashboardLayout({ children }: { children: React.ReactNode }) {
  const locale = await getRequestLocale();
  return <DashboardShell locale={locale}>{children}</DashboardShell>;
}
