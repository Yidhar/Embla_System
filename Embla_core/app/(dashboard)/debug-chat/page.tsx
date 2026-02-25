import { DebugChatConsole } from "@/components/debug/debug-chat-console";
import { resolveLangFromSearchParams } from "@/lib/i18n";

export const dynamic = "force-dynamic";

type DebugChatPageProps = {
  searchParams?: Promise<Record<string, string | string[] | undefined>>;
};

export default async function DebugChatPage({ searchParams }: DebugChatPageProps) {
  const lang = await resolveLangFromSearchParams(searchParams);
  return <DebugChatConsole lang={lang} />;
}
