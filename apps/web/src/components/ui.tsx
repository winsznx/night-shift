/**
 * The component vocabulary, straight from DESIGN.md.
 *
 * Borders define containers, not shadows. Three radii: 9999px for pills, 8px for
 * buttons, 12px for cards, 16px for large feature surfaces. One chromatic accent per
 * component. Satoshi only at 36px and up.
 */
import Link from "next/link";
import type { ReactNode } from "react";

export function Card({
  children,
  className = "",
  padded = true,
}: {
  children: ReactNode;
  className?: string;
  padded?: boolean;
}) {
  return (
    <div
      className={`ns-panel rounded-[12px] border border-[#e5e5e5] bg-white ${padded ? "p-4" : ""} ${className}`}
    >
      {children}
    </div>
  );
}

export function CardHeader({
  title,
  subtitle,
  right,
}: {
  title: string;
  subtitle?: string;
  right?: ReactNode;
}) {
  return (
    <div className="flex items-start justify-between gap-4 border-b border-[#e5e5e5] px-4 py-3">
      <div className="min-w-0">
        <h2 className="text-[14px] font-semibold text-[#171717]">{title}</h2>
        {subtitle ? <p className="mt-0.5 text-[12px] text-[#737373]">{subtitle}</p> : null}
      </div>
      {right ? <div className="shrink-0">{right}</div> : null}
    </div>
  );
}

type Tone = "neutral" | "blue" | "green" | "orange" | "violet" | "red";

const TONE: Record<Tone, string> = {
  neutral: "bg-[#f5f5f5] text-[#404040] border-[#e5e5e5]",
  blue: "bg-[#dbeafe] text-[#1e40af] border-[#bfdbfe]",
  green: "bg-[#dcfce7] text-[#166534] border-[#bbf7d0]",
  orange: "bg-[#fff7ed] text-[#9a3412] border-[#fed7aa]",
  violet: "bg-[#f5f3ff] text-[#5b21b6] border-[#ddd6fe]",
  red: "bg-[#fef2f2] text-[#991b1b] border-[#fecaca]",
};

const DOT: Record<Tone, string> = {
  neutral: "bg-[#a3a3a3]",
  blue: "bg-[#2563eb]",
  green: "bg-[#16a34a]",
  orange: "bg-[#ea580c]",
  violet: "bg-[#7c3aed]",
  red: "bg-[#dc2626]",
};

export function Badge({
  children,
  tone = "neutral",
  dot = false,
}: {
  children: ReactNode;
  tone?: Tone;
  dot?: boolean;
}) {
  return (
    <span
      className={`inline-flex items-center gap-1.5 rounded-full border px-2.5 py-[3px] text-[11px] font-medium whitespace-nowrap ${TONE[tone]}`}
    >
      {dot ? <span className={`h-1.5 w-1.5 rounded-full ${DOT[tone]}`} /> : null}
      {children}
    </span>
  );
}

/** Incident states carry operational meaning; the colour has to match the meaning. */
export function stateTone(state: string): Tone {
  if (state === "CLOSED") return "green";
  if (state === "PARTIAL" || state === "ESCALATED") return "red";
  if (state === "NEEDS_REASSESSMENT" || state === "ABORTED_SAFE") return "orange";
  if (state === "OBSERVING") return "neutral";
  return "blue";
}

export function custodyTone(state: string): Tone {
  if (state === "COMMITTED") return "green";
  if (state === "UNRESOLVED") return "red";
  if (state === "QUARANTINED") return "orange";
  if (state === "AT_SOURCE") return "neutral";
  return "blue";
}

export function StateBadge({ state }: { state: string }) {
  return (
    <Badge tone={stateTone(state)} dot>
      {state.replace(/_/g, " ")}
    </Badge>
  );
}

export function Metric({
  label,
  value,
  hint,
  tone,
}: {
  label: string;
  value: ReactNode;
  hint?: string;
  tone?: "default" | "warn" | "bad" | "good";
}) {
  const color =
    tone === "bad"
      ? "text-[#dc2626]"
      : tone === "warn"
        ? "text-[#ea580c]"
        : tone === "good"
          ? "text-[#16a34a]"
          : "text-[#171717]";
  return (
    <div className="ns-route min-w-0 pl-3">
      <div className="text-[11px] font-medium tracking-wide text-[#737373] uppercase">
        {label}
      </div>
      <div className={`mono mt-1 text-[24px] leading-none font-medium ${color}`}>{value}</div>
      {hint ? <div className="mt-1 text-[12px] text-[#737373]">{hint}</div> : null}
    </div>
  );
}

export function Button({
  children,
  href,
  variant = "outline",
  onClick,
  type = "button",
  disabled = false,
  className = "",
}: {
  children: ReactNode;
  href?: string;
  variant?: "primary" | "outline" | "ghost";
  onClick?: () => void;
  type?: "button" | "submit";
  disabled?: boolean;
  className?: string;
}) {
  const base =
    "inline-flex items-center justify-center gap-2 rounded-[8px] px-4 py-2 text-[14px] font-medium transition-colors disabled:opacity-50 disabled:cursor-not-allowed";
  const styles = {
    primary: "bg-black text-white hover:bg-[#171717] shadow-[rgba(0,0,0,0.05)_0px_1px_2px_0px]",
    outline: "border border-[#e5e5e5] bg-white text-[#171717] hover:bg-[#f5f5f5]",
    ghost: "text-[#171717] hover:bg-[#f5f5f5]",
  }[variant];
  const cls = `${base} ${styles} ${className}`;

  if (href) {
    return (
      <Link href={href} className={cls}>
        {children}
      </Link>
    );
  }
  return (
    <button type={type} onClick={onClick} disabled={disabled} className={cls}>
      {children}
    </button>
  );
}

export function Mono({ children, className = "" }: { children: ReactNode; className?: string }) {
  return <span className={`mono text-[12px] text-[#525252] ${className}`}>{children}</span>;
}

export function Table({
  headers,
  children,
  minWidth = 0,
}: {
  headers: string[];
  children: ReactNode;
  minWidth?: number;
}) {
  return (
    <div className="scroll-x relative">
      <table
        className="w-full border-collapse text-left"
        style={minWidth ? { minWidth: `${minWidth}px` } : undefined}
      >
        <thead>
          <tr className="bg-[#fafafa]">
            {headers.map((h) => (
              <th
                key={h}
                className="border-b border-[#e5e5e5] px-4 py-2.5 text-[11px] font-semibold tracking-[0.08em] text-[#737373] uppercase whitespace-nowrap first:before:mr-2 first:before:inline-block first:before:h-1.5 first:before:w-1.5 first:before:rounded-full first:before:bg-[#2563eb] first:before:content-['']"
              >
                {h}
              </th>
            ))}
          </tr>
        </thead>
        <tbody>{children}</tbody>
      </table>
    </div>
  );
}

export function Td({
  children,
  className = "",
  colSpan,
}: {
  children: ReactNode;
  className?: string;
  colSpan?: number;
}) {
  return (
    <td
      colSpan={colSpan}
      className={`border-b border-[#e5e5e5] px-4 py-2.5 align-middle text-[14px] text-[#171717] ${className}`}
    >
      {children}
    </td>
  );
}

export function Empty({ title, body }: { title: string; body: string }) {
  return (
    <div className="px-4 py-10 text-center">
      <p className="text-[14px] font-medium text-[#171717]">{title}</p>
      <p className="mx-auto mt-1 max-w-[46ch] text-[13px] text-[#737373]">{body}</p>
    </div>
  );
}

export function SyntheticBanner({ compact = false }: { compact?: boolean }) {
  return (
    <div
      className={`flex items-center gap-2 rounded-[8px] border border-[#fed7aa] bg-[#fff7ed] px-3 ${compact ? "py-1.5" : "py-2"}`}
    >
      <span className="h-1.5 w-1.5 shrink-0 rounded-full bg-[#ea580c]" />
      <p className="text-[12px] text-[#9a3412]">
        <span className="font-semibold">Synthetic environment.</span> All estate and
        specimen data is generated. Responder movements are simulated — no real biobank
        samples were moved.
      </p>
    </div>
  );
}

export function InvariantRow({ result }: { result: { invariant: string; title: string; holds: boolean; detail: string } }) {
  return (
    <tr>
      <Td className="w-[64px]">
        <Badge tone={result.holds ? "green" : "red"} dot>
          {result.holds ? "PASS" : "FAIL"}
        </Badge>
      </Td>
      <Td className="w-[56px]">
        <Mono className="font-medium">{result.invariant}</Mono>
      </Td>
      <Td className="font-medium whitespace-nowrap">{result.title}</Td>
      <Td className="text-[13px] text-[#525252]">{result.detail}</Td>
    </tr>
  );
}

export function timeAgo(iso: string, now?: string): string {
  const then = new Date(iso).getTime();
  const base = now ? new Date(now).getTime() : Date.now();
  const seconds = Math.max(0, Math.round((base - then) / 1000));
  if (seconds < 60) return `${seconds}s ago`;
  if (seconds < 3600) return `${Math.round(seconds / 60)}m ago`;
  if (seconds < 86400) return `${Math.round(seconds / 3600)}h ago`;
  return `${Math.round(seconds / 86400)}d ago`;
}

export function clock(iso: string): string {
  return new Date(iso).toISOString().slice(11, 19) + "Z";
}
