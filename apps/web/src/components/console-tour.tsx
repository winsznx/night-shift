"use client";

/**
 * The hero console, walked rather than posed.
 *
 * A single screenshot of an overview page says "here is a dashboard". Moving through
 * Overview → Incident → Fleet → Drills → Evidence says "here is a system that carries a
 * rescue from an alarm to a signed proof", which is the actual claim. The rail highlight
 * travels, the panel crossfades, and a judge who never clicks anything still sees the
 * whole product.
 *
 * Every panel is real data rendered by the server. This component only decides which one
 * is on screen; it never invents a frame.
 *
 * It stops moving whenever a person might be reading: on hover, on keyboard focus, when
 * scrolled out of view, and permanently if the viewer asked for reduced motion.
 */

import { useCallback, useEffect, useRef, useState } from "react";
import type { ReactNode } from "react";

export interface TourStop {
  id: string;
  label: string;
  /** Rail dot colour, so the moving highlight also carries state meaning. */
  tone?: "blue" | "orange" | "green";
  panel: ReactNode;
}

const DWELL_MS = 5200;

export function ConsoleTour({ stops, footnote }: { stops: TourStop[]; footnote?: string }) {
  const [active, setActive] = useState(0);
  const [paused, setPaused] = useState(false);
  const [reducedMotion, setReducedMotion] = useState(false);
  const [visible, setVisible] = useState(true);
  const frameRef = useRef<HTMLDivElement | null>(null);

  useEffect(() => {
    const query = window.matchMedia("(prefers-reduced-motion: reduce)");
    const sync = () => setReducedMotion(query.matches);
    sync();
    query.addEventListener("change", sync);
    return () => query.removeEventListener("change", sync);
  }, []);

  // A console that keeps cycling off-screen is wasted work and a background distraction.
  useEffect(() => {
    const node = frameRef.current;
    if (!node || typeof IntersectionObserver === "undefined") return;
    const observer = new IntersectionObserver(
      ([entry]) => setVisible(entry.isIntersecting),
      { threshold: 0.25 },
    );
    observer.observe(node);
    return () => observer.disconnect();
  }, []);

  const running = !paused && !reducedMotion && visible && stops.length > 1;

  useEffect(() => {
    if (!running) return;
    const timer = window.setTimeout(
      () => setActive((current) => (current + 1) % stops.length),
      DWELL_MS,
    );
    return () => window.clearTimeout(timer);
  }, [running, active, stops.length]);

  const go = useCallback((index: number) => {
    setActive(index);
  }, []);

  return (
    // flex column, not a bare block: panels vary in height, and when a short one was
    // active the grid row collapsed to its content. The rail's tinted background stopped
    // partway down and left a square-cornered white gap inside the rounded frame. The
    // body must own the remaining height regardless of which panel is showing.
    <div
      ref={frameRef}
      className="relative flex h-[390px] flex-col overflow-hidden rounded-[16px] border border-[#e5e5e5] bg-white shadow-[rgba(0,0,0,0.1)_0px_0px_0px_4px] sm:h-[460px] lg:h-[560px]"
      onMouseEnter={() => setPaused(true)}
      onMouseLeave={() => setPaused(false)}
      onFocusCapture={() => setPaused(true)}
      onBlurCapture={() => setPaused(false)}
    >
      <div className="absolute top-0 right-0 z-[2] border-b border-l border-[#bfdbfe] bg-[#eff6ff] px-3 py-1.5">
        <span className="mono text-[10px] font-medium tracking-[0.08em] text-[#1e40af] uppercase">
          Live command surface
        </span>
      </div>

      <TourHeader stop={stops[active]} />

      {/* The rail is desktop-only, so without this a phone shows content quietly swapping
          itself with nothing to explain why. */}
      {stops.length > 1 ? (
        <div className="flex shrink-0 items-center gap-1.5 border-b border-[#e5e5e5] bg-white px-3 py-2 lg:hidden">
          {stops.map((stop, index) => (
            <button
              key={stop.id}
              type="button"
              onClick={() => go(index)}
              aria-current={index === active ? "true" : undefined}
              aria-label={stop.label}
              className={`rounded-full px-2.5 py-1 text-[11px] transition-colors ${
                index === active
                  ? "bg-[#dbeafe] font-medium text-[#171717]"
                  : "text-[#737373]"
              }`}
            >
              {stop.label}
            </button>
          ))}
        </div>
      ) : null}

      <div className="grid min-h-0 flex-1 lg:grid-cols-[188px_1fr]">
        <TourRail
          stops={stops}
          active={active}
          onSelect={go}
          running={running}
          footnote={footnote}
        />

        <div className="relative min-h-0 overflow-hidden">
          {stops.map((stop, index) => (
            <div
              key={stop.id}
              aria-hidden={index !== active}
              className={
                index === active
                  ? "tour-panel-enter h-full"
                  : "pointer-events-none absolute inset-0 opacity-0"
              }
              style={index === active ? undefined : { visibility: "hidden" }}
            >
              {stop.panel}
            </div>
          ))}
        </div>
      </div>
    </div>
  );
}

function TourHeader({ stop }: { stop: TourStop }) {
  return (
    <div className="flex items-center gap-2 border-b border-[#e5e5e5] bg-[#fafafa] px-3 py-2">
      <span className="flex gap-1.5">
        {["#f87171", "#fbbf24", "#34d399"].map((c) => (
          <span key={c} className="h-2 w-2 rounded-full" style={{ background: c }} />
        ))}
      </span>
      <span className="mono ml-2 truncate text-[11px] text-[#737373]">
        nightshift / {stop.label.toLowerCase()}
      </span>
    </div>
  );
}

function TourRail({
  stops,
  active,
  onSelect,
  running,
  footnote,
}: {
  stops: TourStop[];
  active: number;
  onSelect: (index: number) => void;
  running: boolean;
  footnote?: string;
}) {
  return (
    <aside className="hidden h-full flex-col border-r border-[#e5e5e5] bg-[#fafafa] p-3 lg:flex">
      <p className="mono px-2 pb-3 text-[10px] tracking-[0.1em] text-[#737373] uppercase">
        Operations
      </p>
      <nav className="space-y-1" aria-label="Command console preview">
        {stops.map((stop, index) => {
          const current = index === active;
          const dot =
            stop.tone === "orange" ? "#ea580c" : stop.tone === "green" ? "#16a34a" : "#2563eb";
          return (
            <button
              key={stop.id}
              type="button"
              onClick={() => onSelect(index)}
              aria-current={current ? "true" : undefined}
              className={`relative flex w-full items-center gap-2 overflow-hidden rounded-[7px] px-2.5 py-2 text-left text-[12px] transition-colors ${
                current
                  ? "bg-[#dbeafe] font-medium text-[#171717]"
                  : "text-[#525252] hover:bg-[#f0f0f0]"
              }`}
            >
              <span
                className="h-1.5 w-1.5 shrink-0 rounded-full transition-colors"
                style={{ background: current ? dot : "#d4d4d4" }}
              />
              {stop.label}
              {current && running ? (
                <span
                  key={`${stop.id}-${active}`}
                  className="tour-dwell absolute bottom-0 left-0 h-[2px] bg-[#2563eb]"
                />
              ) : null}
            </button>
          );
        })}
      </nav>
      <div className="mt-6 rounded-[8px] border border-[#dbeafe] bg-white p-2.5">
        <p className="mono text-[9px] text-[#1e40af]">RUN STATE</p>
        <p className="mt-1 text-[11px] font-medium text-[#171717]">Evidence attached</p>
      </div>

      {/* Pinned to the bottom of the rail so the tinted column always reaches the frame's
          rounded edge, whatever the active panel's height. */}
      {footnote ? (
        <p className="mt-auto px-2 pt-3 text-[11px] leading-snug text-[#737373]">{footnote}</p>
      ) : null}
    </aside>
  );
}
