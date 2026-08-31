import Link from "next/link";

import { Logo } from "@/components/shell";
import { Button, Card, Mono } from "@/components/ui";

/**
 * Reached only when the API answered and had no such record, or when the URL matched no
 * route at all. An API that failed throws instead and lands on error.tsx, so this page is
 * free to say the thing is absent without guessing.
 */
export default function NotFound() {
  return (
    <div className="thermal-trace min-h-screen bg-white">
      <header className="border-b border-[#e5e5e5]">
        <div className="mx-auto flex max-w-[1000px] items-center justify-between gap-4 px-6 py-3.5">
          <Link href="/">
            <Logo />
          </Link>
          <Link
            href="/app"
            className="rounded-[8px] border border-[#e5e5e5] px-4 py-1.5 text-[14px] font-medium hover:bg-[#f5f5f5]"
          >
            Open console
          </Link>
        </div>
      </header>

      <main className="mx-auto max-w-[820px] px-6 py-14">
        <p className="ns-eyebrow">404 · not found</p>
        <h1 className="mt-2 max-w-[24ch] text-[34px] leading-[1.05] font-semibold tracking-[-0.03em] text-[#171717]">
          Nothing is published at this address
        </h1>
        <p className="mt-3 max-w-[70ch] text-[16px] leading-relaxed text-[#525252]">
          Either the URL does not match a route, or the record it names has never existed in
          this environment. The estate is regenerated per deployment, so an incident, drill,
          or responder id copied from a different run will not resolve here.
        </p>

        <Card className="mt-7">
          <h2 className="text-[14px] font-semibold text-[#171717]">
            This is not an outage message
          </h2>
          <p className="mt-1.5 max-w-[78ch] text-[13px] leading-relaxed text-[#525252]">
            The API was reached and it reported no such record. Had the API failed instead,
            you would be looking at the error page, which says so plainly rather than
            calling a working record missing. The two cases are kept apart on purpose, in{" "}
            <Mono>src/lib/api.ts</Mono>, because a product that claims to know what is true
            has no business guessing which one happened.
          </p>
        </Card>

        <div className="mt-7 flex flex-wrap gap-2">
          <Button href="/app" variant="primary">
            Open console
          </Button>
          <Button href="/app/incidents">Browse incidents</Button>
          <Button href="/app/drills">Browse drills</Button>
          <Button href="/verify" variant="ghost">
            Verify the evidence
          </Button>
        </div>
      </main>
    </div>
  );
}
