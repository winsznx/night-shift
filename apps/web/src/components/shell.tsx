/**
 * The operator app shell: fixed sidebar plus content area, the same 2-column shape the
 * landing-page mockup shows.
 */
import Link from "next/link";
import type { ReactNode } from "react";

import { getMeta } from "@/lib/api";
import { Mono } from "@/components/ui";

const NAV = [
  { href: "/app", label: "Overview" },
  { href: "/app/incidents", label: "Incidents" },
  { href: "/app/freezers", label: "Freezers" },
  { href: "/app/capacity", label: "Capacity" },
  { href: "/app/fleet", label: "Fleet" },
  { href: "/app/drills", label: "Drills" },
  { href: "/app/evidence", label: "Evidence" },
];

export function Logo({ size = 14 }: { size?: number }) {
  return (
    <span className="inline-flex items-center gap-2">
      <span className="relative inline-grid place-items-center" style={{ width: size, height: size }} aria-hidden>
        <span className="absolute inset-0 rounded-full border border-[#2563eb]/40" />
        <span className="h-[38%] w-[38%] rounded-full bg-[#2563eb]" />
        <span className="absolute right-[-18%] bottom-[5%] h-px w-[45%] bg-[#2563eb]" />
      </span>
      <span
        className="font-semibold tracking-[-0.01em] text-[#0a0a0a]"
        style={{ fontSize: size }}
      >
        Night Shift
      </span>
    </span>
  );
}

export async function AppShell({
  children,
  active,
}: {
  children: ReactNode;
  active: string;
}) {
  const meta = await getMeta();

  return (
    <div className="min-h-screen bg-white">
      <div className="mx-auto flex max-w-[1400px]">
        <aside className="sticky top-0 hidden h-screen w-[228px] shrink-0 flex-col border-r border-[#e5e5e5] bg-white px-3 py-4 lg:flex">
          <Link href="/" className="px-2 pb-4">
            <Logo />
          </Link>
          <nav className="flex flex-col gap-0.5">
            {NAV.map((item) => {
              const isActive =
                item.href === "/app" ? active === "/app" : active.startsWith(item.href);
              return (
                <Link
                  key={item.href}
                  href={item.href}
                  aria-current={isActive ? "page" : undefined}
                  className={`relative rounded-[8px] px-2 py-[9px] text-[14px] transition-colors ${
                    isActive
                      ? "bg-[#dbeafe] font-medium text-[#171717] before:absolute before:top-1/2 before:left-[-13px] before:h-4 before:w-0.5 before:-translate-y-1/2 before:bg-[#2563eb]"
                      : "text-[#404040] hover:bg-[#f5f5f5]"
                  }`}
                >
                  {item.label}
                </Link>
              );
            })}
          </nav>

          <div className="ns-route mt-5 px-3 py-2 pl-4">
            <p className="mono text-[10px] tracking-[0.12em] text-[#737373] uppercase">Control plane</p>
            <p className="mt-1 text-[12px] leading-snug text-[#525252]">Operational state, authority boundaries, and independently checkable proof.</p>
          </div>

          <div className="mt-auto space-y-2 border-t border-[#e5e5e5] pt-3">
            <div className="rounded-[8px] border border-[#fed7aa] bg-[#fff7ed] px-2.5 py-2">
              <p className="text-[11px] leading-snug text-[#9a3412]">
                <span className="font-semibold">Synthetic data.</span> Field events are
                simulated.
              </p>
            </div>
            {meta ? (
              <dl className="space-y-1 px-2 text-[11px] text-[#737373]">
                <div className="flex justify-between gap-2">
                  <dt>model</dt>
                  <dd className="mono truncate text-[#525252]">{meta.model_id}</dd>
                </div>
                <div className="flex justify-between gap-2">
                  <dt>store</dt>
                  <dd className="mono text-[#525252]">{meta.store_backend}</dd>
                </div>
                <div className="flex justify-between gap-2">
                  <dt>signer</dt>
                  <dd className="mono text-[#525252]">{meta.signer_backend}</dd>
                </div>
                <div className="flex justify-between gap-2">
                  <dt>env</dt>
                  <dd className="mono text-[#525252]">{meta.deployment_env}</dd>
                </div>
              </dl>
            ) : null}
          </div>
        </aside>

        <div className="min-w-0 flex-1">
          <header className="sticky top-0 z-10 flex items-center justify-between gap-4 border-b border-[#e5e5e5] bg-white/92 px-4 py-3 backdrop-blur lg:px-6">
            <Link href="/" className="lg:hidden">
              <Logo size={13} />
            </Link>
            <nav className="scroll-x flex gap-1 lg:hidden">
              {NAV.map((item) => (
                <Link
                  key={item.href}
                  href={item.href}
                  className="rounded-full px-3 py-1 text-[13px] whitespace-nowrap text-[#404040] hover:bg-[#f5f5f5]"
                >
                  {item.label}
                </Link>
              ))}
            </nav>
            <div className="ml-auto hidden items-center gap-3 lg:flex">
              <Mono>{meta?.region ?? "us-central1"}</Mono>
              <Mono>{(meta?.source_commit ?? "local").slice(0, 10)}</Mono>
            </div>
          </header>
          {/* The sidebar carries this notice, and the sidebar is hidden below lg. Without
              a mobile copy, a phone viewer sees no synthetic-data labelling at all, the
              one disclosure that must never depend on viewport width. */}
          <div className="border-b border-[#fed7aa] bg-[#fff7ed] px-4 py-2 lg:hidden">
            <p className="text-[11px] leading-snug text-[#9a3412]">
              <span className="font-semibold">Synthetic data.</span> Field events are
              simulated.
            </p>
          </div>
          <main className="thermal-trace min-h-[calc(100vh-53px)] px-4 py-5 lg:px-6 lg:py-6">{children}</main>
        </div>
      </div>
    </div>
  );
}

export function PageHeader({
  title,
  subtitle,
  right,
}: {
  title: string;
  subtitle?: string;
  right?: ReactNode;
}) {
  return (
    <div className="mb-5 flex flex-wrap items-end justify-between gap-3 border-b border-[#e5e5e5] pb-4">
      <div className="min-w-0">
        <p className="ns-eyebrow mb-2">Night Shift / {title}</p>
        <h1 className="text-[24px] leading-tight font-semibold tracking-[-0.025em] text-[#171717]">{title}</h1>
        {subtitle ? (
          <p className="mt-1 max-w-[70ch] text-[14px] text-[#737373]">{subtitle}</p>
        ) : null}
      </div>
      {right ? <div className="flex shrink-0 items-center gap-2">{right}</div> : null}
    </div>
  );
}

export function ApiDown({ what }: { what: string }) {
  return (
    <div className="rounded-[12px] border border-[#fecaca] bg-[#fef2f2] p-4">
      <p className="text-[14px] font-medium text-[#991b1b]">
        {what} is unavailable right now.
      </p>
      <p className="mt-1 text-[13px] text-[#991b1b]">
        The API did not respond. Nothing is being shown from cache or guessed. This page
        stays empty rather than displaying stale operational state.
      </p>
    </div>
  );
}
