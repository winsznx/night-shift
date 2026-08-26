"use client";

import { useState, useTransition } from "react";

import type { ResponderTask, ResponderView } from "@/lib/api";

/**
 * The responder screen.
 *
 * Not a chat surface. One container at a time, big targets, and the destination
 * temperature front and centre — because that is the number that decides whether the
 * commit will be accepted, and a responder should know before they walk.
 */
export function ResponderClient({ token, initial }: { token: string; initial: ResponderView }) {
  const [view, setView] = useState(initial);
  const [pending, startTransition] = useTransition();
  const [message, setMessage] = useState<{ tone: "ok" | "bad"; text: string } | null>(null);
  const [code, setCode] = useState("");

  const active = view.tasks.filter(
    (t) => !["COMMITTED", "QUARANTINED"].includes(t.custody_state),
  );
  const current = active[0] ?? null;

  async function post(action: "pickup" | "receive" | "exception", body: Record<string, unknown>) {
    setMessage(null);
    const response = await fetch(`/api/respond/${token}/${action}`, {
      method: "POST",
      headers: { "content-type": "application/json" },
      body: JSON.stringify(body),
    });
    const data = await response.json().catch(() => ({}));

    if (!response.ok) {
      setMessage({
        tone: "bad",
        text: String(data?.detail?.reason ?? data?.detail?.error ?? "The request was refused."),
      });
    } else {
      const receipt = data?.receipt ?? data?.commit?.receipt;
      const decision = data?.commit?.decision ?? data?.decision;
      if (receipt?.status === "REFUSED") {
        setMessage({
          tone: "bad",
          text: `Refused by ${decision?.invariant ?? "the safety kernel"}: ${decision?.reason ?? "precondition not met"}`,
        });
      } else if (receipt?.duplicate_returned) {
        setMessage({ tone: "ok", text: "Already recorded. Returning the original receipt." });
      } else {
        setMessage({ tone: "ok", text: "Recorded." });
      }
    }

    const refreshed = await fetch(`/api/respond/${token}`).then((r) => (r.ok ? r.json() : null));
    if (refreshed) setView(refreshed as ResponderView);
    setCode("");
  }

  return (
    <div className="mx-auto max-w-[560px] px-4 pb-24">
      <Summary view={view} />

      {message ? (
        <div
          role="status"
          className={`mt-3 rounded-[8px] border px-3 py-2.5 text-[14px] ${
            message.tone === "ok"
              ? "border-[#bbf7d0] bg-[#dcfce7] text-[#166534]"
              : "border-[#fecaca] bg-[#fef2f2] text-[#991b1b]"
          }`}
        >
          {message.text}
        </div>
      ) : null}

      {current ? (
        <TaskCard
          task={current}
          code={code}
          setCode={setCode}
          pending={pending}
          onPickup={() =>
            startTransition(() => {
              void post("pickup", { container_id: current.container_id });
            })
          }
          onReceive={() =>
            startTransition(() => {
              void post("receive", {
                container_id: current.container_id,
                location_ref: code.trim() || current.destination_freezer || "",
              });
            })
          }
          onException={(reason) =>
            startTransition(() => {
              void post("exception", {
                container_id: current.container_id,
                reason,
                disposition: "UNRESOLVED",
              });
            })
          }
        />
      ) : (
        <div className="mt-4 rounded-[12px] border border-[#bbf7d0] bg-[#dcfce7] p-5 text-center">
          <p className="text-[16px] font-semibold text-[#166534]">Batch complete</p>
          <p className="mt-1 text-[14px] text-[#166534]">
            Every container in this batch has reached a terminal state.
          </p>
        </div>
      )}

      <Remaining tasks={view.tasks} />
    </div>
  );
}

function Summary({ view }: { view: ResponderView }) {
  const s = view.summary;
  return (
    <div className="mt-3 rounded-[12px] border border-[#e5e5e5] bg-white p-4">
      <div className="flex items-center justify-between gap-2">
        <span className="mono text-[12px] text-[#737373]">{view.incident_id}</span>
        <span className="rounded-full border border-[#bfdbfe] bg-[#dbeafe] px-2.5 py-[3px] text-[11px] font-medium text-[#1e40af]">
          {view.response_phase}
        </span>
      </div>
      <p className="mt-2 text-[15px] font-medium text-[#171717]">
        Move material out of {view.failed_freezer_id}
      </p>
      <div className="mt-3 grid grid-cols-4 gap-2 text-center">
        {[
          ["To move", s.at_source],
          ["In transit", s.picked_up],
          ["Done", s.committed],
          ["Flagged", s.exceptions],
        ].map(([label, value]) => (
          <div key={String(label)} className="rounded-[8px] bg-[#f5f5f5] py-2">
            <div className="mono text-[18px] leading-none font-medium text-[#171717]">
              {String(value)}
            </div>
            <div className="mt-1 text-[11px] text-[#737373]">{label}</div>
          </div>
        ))}
      </div>
    </div>
  );
}

function TaskCard({
  task,
  code,
  setCode,
  pending,
  onPickup,
  onReceive,
  onException,
}: {
  task: ResponderTask;
  code: string;
  setCode: (v: string) => void;
  pending: boolean;
  onPickup: () => void;
  onReceive: () => void;
  onException: (reason: string) => void;
}) {
  const needsPickup = task.custody_state === "AT_SOURCE";
  const tempOk =
    task.destination_temp_c !== null &&
    task.destination_temp_c <= -60 &&
    (task.destination_reading_age_s ?? 0) <= 900;

  return (
    <div className="mt-3 rounded-[12px] border border-[#e5e5e5] bg-white">
      <div className="border-b border-[#e5e5e5] px-4 py-3">
        <div className="flex items-center justify-between gap-2">
          <span className="mono text-[18px] font-medium text-[#171717]">
            {task.container_id}
          </span>
          <span className="rounded-full border border-[#e5e5e5] bg-[#f5f5f5] px-2.5 py-[3px] text-[11px] font-medium text-[#404040]">
            {task.custody_state.replace(/_/g, " ")}
          </span>
        </div>
      </div>

      <div className="grid grid-cols-2 divide-x divide-[#e5e5e5] border-b border-[#e5e5e5]">
        <div className="px-4 py-3">
          <div className="text-[11px] tracking-wide text-[#737373] uppercase">From</div>
          <div className="mono mt-1 text-[15px] font-medium text-[#171717]">
            {task.source_freezer}
          </div>
          <div className="mono mt-0.5 text-[12px] text-[#737373]">{task.source_slot}</div>
        </div>
        <div className="px-4 py-3">
          <div className="text-[11px] tracking-wide text-[#737373] uppercase">To</div>
          <div className="mono mt-1 text-[15px] font-medium text-[#171717]">
            {task.destination_freezer ?? "—"}
          </div>
          <div className="mono mt-0.5 text-[12px] text-[#737373]">
            {task.destination_slot ?? "awaiting reservation"}
          </div>
        </div>
      </div>

      {task.destination_freezer ? (
        <div
          className={`flex items-center justify-between gap-3 border-b border-[#e5e5e5] px-4 py-3 ${
            tempOk ? "bg-[#dcfce7]" : "bg-[#fef2f2]"
          }`}
        >
          <div>
            <div
              className={`text-[11px] tracking-wide uppercase ${tempOk ? "text-[#166534]" : "text-[#991b1b]"}`}
            >
              Destination temperature
            </div>
            <div
              className={`mono mt-0.5 text-[20px] leading-none font-medium ${tempOk ? "text-[#166534]" : "text-[#991b1b]"}`}
            >
              {task.destination_temp_c !== null
                ? `${task.destination_temp_c.toFixed(1)}°C`
                : "no reading"}
            </div>
          </div>
          <div className={`text-right text-[12px] ${tempOk ? "text-[#166534]" : "text-[#991b1b]"}`}>
            {task.destination_reading_age_s !== null
              ? `read ${Math.round(task.destination_reading_age_s)}s ago`
              : "—"}
            <br />
            {tempOk ? "safe to receive" : "commit will be refused"}
          </div>
        </div>
      ) : null}

      {task.exception_reason ? (
        <div className="border-b border-[#e5e5e5] bg-[#fff7ed] px-4 py-3 text-[13px] text-[#9a3412]">
          {task.exception_reason}
        </div>
      ) : null}

      <div className="p-4">
        {needsPickup ? (
          <button
            type="button"
            onClick={onPickup}
            disabled={pending || !task.destination_freezer}
            className="w-full rounded-[8px] bg-black px-4 py-3.5 text-[16px] font-medium text-white disabled:opacity-40"
          >
            {pending ? "Recording…" : "Confirm pickup"}
          </button>
        ) : (
          <>
            <label
              htmlFor="dest-code"
              className="block text-[12px] font-medium text-[#404040]"
            >
              Scan or type the destination freezer code
            </label>
            <input
              id="dest-code"
              value={code}
              onChange={(e) => setCode(e.target.value.toUpperCase())}
              placeholder={task.destination_freezer ?? "F-00"}
              autoComplete="off"
              inputMode="text"
              className="mono mt-1.5 w-full rounded-[6px] border border-black px-3 py-3 text-[16px] text-[#111827]"
            />
            <button
              type="button"
              onClick={onReceive}
              disabled={pending}
              className="mt-2.5 w-full rounded-[8px] bg-black px-4 py-3.5 text-[16px] font-medium text-white disabled:opacity-40"
            >
              {pending ? "Recording…" : "Confirm receipt"}
            </button>
          </>
        )}

        <button
          type="button"
          onClick={() => onException("Responder flagged an exception in the field")}
          disabled={pending}
          className="mt-2 w-full rounded-[8px] border border-[#e5e5e5] px-4 py-3 text-[15px] font-medium text-[#171717] disabled:opacity-40"
        >
          Flag a problem
        </button>
      </div>
    </div>
  );
}

function Remaining({ tasks }: { tasks: ResponderTask[] }) {
  if (tasks.length <= 1) return null;
  return (
    <div className="mt-4 rounded-[12px] border border-[#e5e5e5] bg-white">
      <div className="border-b border-[#e5e5e5] px-4 py-2.5">
        <h2 className="text-[13px] font-semibold text-[#171717]">Batch</h2>
      </div>
      <ul className="max-h-[280px] divide-y divide-[#e5e5e5] overflow-y-auto">
        {tasks.map((t) => (
          <li key={t.container_id} className="flex items-center justify-between gap-2 px-4 py-2">
            <span className="mono text-[13px] text-[#171717]">{t.container_id}</span>
            <span
              className={`rounded-full px-2 py-[2px] text-[11px] font-medium ${
                t.custody_state === "COMMITTED"
                  ? "bg-[#dcfce7] text-[#166534]"
                  : t.custody_state === "UNRESOLVED"
                    ? "bg-[#fef2f2] text-[#991b1b]"
                    : t.custody_state === "AT_SOURCE"
                      ? "bg-[#f5f5f5] text-[#404040]"
                      : "bg-[#dbeafe] text-[#1e40af]"
              }`}
            >
              {t.custody_state.replace(/_/g, " ")}
            </span>
          </li>
        ))}
      </ul>
    </div>
  );
}
