import { redirect } from "next/navigation";
import { resolveLangFromSearchParams } from "@/lib/i18n";

type HomePageProps = {
  searchParams?: Promise<Record<string, string | string[] | undefined>>;
};

export default async function HomePage({ searchParams }: HomePageProps) {
  const lang = await resolveLangFromSearchParams(searchParams);
  const query = lang === "zh-CN" ? "?lang=zh-cn" : "?lang=en";
  redirect(`/runtime-posture${query}`);
}
