/**
 * The incident timeline.
 *
 * Agent reasoning and deterministic receipts are visually distinct on purpose (PRD
 * §35.2). A reader has to be able to tell, at a glance, which entries are a model's
 * opinion and which are a committed effect that actually changed the world.
 */
import { Badge, Mono, clock } from "@/components/ui";
import type { TimelineEvent } from "@/lib/api";

const KIND_LABEL: Record<string, string> = {
  sensor: "Sensor",
  state_transition: "State",
  agent_decision: "Agent decision",
  agent_delegation: "Delegation",
  tool_call: "Tool call",
  receipt: "Receipt",
  refusal: "Refused",
  policy: "Policy",
  security: "Security",
  fault_injection: "Fault injected",
  field: "Field",
  note: "Note",
};

function kindStyle(kind: string): { rail: string; tone: Parameters<typeof Badge>[0]["tone"] } {
  switch (kind) {
    case "receipt":
      return { rail: "bg-[#16a34a]", tone: "green" };
    case "refusal":
      return { rail: "bg-[#dc2626]", tone: "red" };
    case "security":
      return { rail: "bg-[#dc2626]", tone: "red" };
    case "agent_decision":
    case "agent_delegation":
      return { rail: "bg-[#7c3aed]", tone: "violet" };
    case "field":
      return { rail: "bg-[#ea580c]", tone: "orange" };
    case "fault_injection":
      return { rail: "bg-[#ea580c]", tone: "orange" };
    case "sensor":
      return { rail: "bg-[#2563eb]", tone: "blue" };
    default:
      return { rail: "bg-[#a3a3a3]", tone: "neutral" };
  }
}

export function Timeline({ events }: { events: TimelineEvent[] }) {
  if (events.length === 0) {
    return (
      <div className="px-4 py-10 text-center text-[13px] text-[#737373]">
        No events recorded for this incident yet.
      </div>
    );
  }

  return (
    <ol className="divide-y divide-[#e5e5e5]">
      {events.map((event) => {
        const style = kindStyle(event.kind);
        const isDeterministic = event.kind === "receipt" || event.kind === "refusal";
        return (
          <li key={event.event_id} className="flex gap-3 px-4 py-3">
            <span
              className={`mt-[7px] h-2 w-2 shrink-0 rounded-full ${style.rail}`}
              aria-hidden
            />
            <div className="min-w-0 flex-1">
              <div className="flex flex-wrap items-center gap-2">
                <Badge tone={style.tone}>{KIND_LABEL[event.kind] ?? event.kind}</Badge>
                {event.agent ? (
                  <Mono className="text-[11px] text-[#7c3aed]">{event.agent}</Mono>
                ) : (
                  <Mono className="text-[11px]">{event.source}</Mono>
                )}
                <Mono className="ml-auto text-[11px] text-[#a3a3a3]">
                  {clock(event.occurred_at)}
                </Mono>
              </div>
              <p
                className={`mt-1 text-[13px] leading-snug ${
                  isDeterministic ? "font-medium text-[#171717]" : "text-[#404040]"
                }`}
              >
                {event.summary}
              </p>
              <EventDetail event={event} />
            </div>
          </li>
        );
      })}
    </ol>
  );
}

function EventDetail({ event }: { event: TimelineEvent }) {
  const d = event.detail ?? {};
  const chips: string[] = [];

  if (event.action_id) chips.push(`action ${String(event.action_id).slice(0, 12)}…`);
  if (typeof d.effect_ref === "string") chips.push(String(d.effect_ref));
  if (typeof d.invariant === "string") chips.push(`invariant ${d.invariant}`);
  if (typeof d.from === "string" && typeof d.to === "string") {
    chips.push(`${d.from} → ${d.to}`);
  }
  if (Array.isArray(d.evidence_sources) && d.evidence_sources.length) {
    chips.push(`${d.evidence_sources.length} authoritative source(s)`);
  }
  if (typeof d.destination_temp_c === "number") {
    chips.push(`dest ${Number(d.destination_temp_c).toFixed(1)}°C`);
  }
  if (typeof d.specialist === "string") chips.push(`→ ${d.specialist}`);
  if (typeof d.classification === "string") chips.push(String(d.classification));

  if (chips.length === 0) return null;
  return (
    <div className="mt-1.5 flex flex-wrap gap-1.5">
      {chips.map((chip) => (
        <span
          key={chip}
          className="mono rounded-full border border-[#e5e5e5] px-2 py-[1px] text-[11px] text-[#737373]"
        >
          {chip}
        </span>
      ))}
    </div>
  );
}
