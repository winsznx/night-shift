"use client";

import Link from "next/link";

import { Button, Card, Mono } from "@/components/ui";

/**
 * The same mark as components/shell.tsx. It is copied rather than imported because that
 * module also exports AppShell, an async Server Component sitting on the API data layer,
 * and importing it across this client boundary would drag both into the browser bundle.
 */
function Logo({ size = 14 }: { size?: number }) {
  return (
    <span className="inline-flex items-center gap-2">
      <span
        className="relative inline-grid place-items-center"
        style={{ width: size, height: size }}
        aria-hidden
      >
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

/**
 * Reached when a page threw, which for the data-backed routes means the API failed or was
 * unreachable. It must never phrase that as a missing record: notFound() handles genuine
 * absence, and conflating the two is how a dashboard ends up lying about its own estate.
 */
export default function Error({
  error,
  reset,
}: {
  error: Error & { digest?: string };
  reset: () => void;
}) {
  return (
    <div className="thermal-trace min-h-screen bg-white">
      <header className="border-b border-[#e5e5e5]">
        <div className="mx-auto flex max-w-[1000px] items-center justify-between gap-4 px-6 py-3.5">
          <Link href="/">
            <Logo />
          </Link>
          <Link
            href="/verify"
            className="rounded-[8px] border border-[#e5e5e5] px-4 py-1.5 text-[14px] font-medium hover:bg-[#f5f5f5]"
          >
            How to verify
          </Link>
        </div>
      </header>

      <main className="mx-auto max-w-[820px] px-6 py-14">
        <p className="ns-eyebrow">Upstream failure</p>
        <h1 className="mt-2 max-w-[26ch] text-[34px] leading-[1.05] font-semibold tracking-[-0.03em] text-[#171717]">
          This page could not load its data
        </h1>
        <p className="mt-3 max-w-[70ch] text-[16px] leading-relaxed text-[#525252]">
          Something failed between this page and the API. Whatever you were looking at still
          exists as far as anyone here knows, so nothing on this screen should be read as a
          statement about the estate. No cached or guessed operational state is being shown
          in its place.
        </p>

        <div className="mt-7 rounded-[12px] border border-[#fecaca] bg-[#fef2f2] p-4">
          <p className="text-[14px] font-medium text-[#991b1b]">What is known</p>
          <p className="mt-1 max-w-[78ch] text-[13px] leading-relaxed text-[#991b1b]">
            {error.message || "The request failed without a message."}
          </p>
          {error.digest ? (
            <p className="mt-2 text-[13px] text-[#991b1b]">
              Server digest <Mono className="text-[#991b1b]">{error.digest}</Mono>
            </p>
          ) : null}
        </div>

        <Card className="mt-4">
          <h2 className="text-[14px] font-semibold text-[#171717]">
            The signed evidence does not depend on this
          </h2>
          <p className="mt-1.5 max-w-[78ch] text-[13px] leading-relaxed text-[#525252]">
            Published manifests are committed to the repository and verify offline with no
            network and no credentials. If the console is down, the proof still checks:{" "}
            <Mono>python -m nightshift.verify --manifest evidence/incidents/INC-0E7C54F8B5.manifest.json</Mono>
          </p>
        </Card>

        <div className="mt-7 flex flex-wrap gap-2">
          <Button onClick={reset} variant="primary">
            Try again
          </Button>
          <Button href="/app">Open console</Button>
          <Button href="/verify" variant="ghost">
            Verify the evidence
          </Button>
        </div>
      </main>
    </div>
  );
}
