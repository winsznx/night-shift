import { notFound } from "next/navigation";

import { getResponderView } from "@/lib/api";
import { ResponderClient } from "./responder-client";

export const dynamic = "force-dynamic";

export default async function RespondPage({
  params,
}: {
  params: Promise<{ taskToken: string }>;
}) {
  const { taskToken } = await params;
  const view = await getResponderView(taskToken);
  if (!view) notFound();

  return (
    <div className="thermal-trace min-h-screen bg-[#f5f5f5]">
      <header className="sticky top-0 z-10 border-b border-[#e5e5e5] bg-white px-4 py-3">
        <div className="mx-auto flex max-w-[560px] items-center justify-between gap-3">
          <span className="inline-flex items-center gap-2">
            <span className="relative inline-grid h-3 w-3 place-items-center" aria-hidden>
              <span className="absolute inset-0 rounded-full border border-[#2563eb]/40" />
              <span className="h-1 w-1 rounded-full bg-[#2563eb]" />
            </span>
            <span className="text-[14px] font-semibold tracking-[-0.01em] text-[#0a0a0a]">Night Shift</span>
          </span>
          <span className="text-[12px] text-[#737373]">{view.responder_id}</span>
        </div>
      </header>

      <div className="mx-auto max-w-[560px] px-4 pt-3">
        <div className="flex items-center gap-2 rounded-[8px] border border-[#fed7aa] bg-[#fff7ed] px-3 py-2">
          <span className="h-1.5 w-1.5 shrink-0 rounded-full bg-[#ea580c]" aria-hidden />
          <p className="text-[12px] text-[#9a3412]">
            Synthetic environment. No real specimens are being moved.
          </p>
        </div>
      </div>

      <ResponderClient token={taskToken} initial={view} />
    </div>
  );
}
