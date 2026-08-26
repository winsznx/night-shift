import Image from "next/image";
import Link from "next/link";

import { Logo } from "@/components/shell";
import { Badge, Card, Mono } from "@/components/ui";
import { ConsoleTour } from "@/components/console-tour";
import { getDrills, getEvidence, getFleet, getOverview } from "@/lib/api";

export const dynamic = "force-dynamic";

export default async function Landing() {
  const [overview, drills, evidence, fleet] = await Promise.all([
    getOverview(),
    getDrills(),
    getEvidence(),
    getFleet(),
  ]);

  const scripted = drills?.campaign?.by_driver?.scripted;
  const agent = drills?.campaign?.by_driver?.agent;
  const headline = overview?.incidents?.[0];

  return (
    <div className="min-h-screen bg-white">
      {/* The hero is intentionally a bounded command room: public copy above, the real
          operational surface emerging beneath it. */}
      <div className="bg-[#f5f5f5] px-3 py-3 sm:px-6 sm:py-6 lg:px-10 lg:py-10">
      <section className="dotgrid relative mx-auto max-w-[1420px] overflow-hidden rounded-[24px] border border-[#d4d4d4] bg-white shadow-[0_20px_60px_rgba(10,10,10,0.08)]">
        <Nav />
        <Image
          src="/brand/thermal-proof.webp"
          sizes="(max-width: 1280px) 620px, 760px"
          alt=""
          width={1448}
          height={1086}
          priority
          className="pointer-events-none absolute top-[-88px] right-[-275px] hidden w-[620px] opacity-55 lg:block xl:right-[-180px] xl:w-[760px]"
        />
        <div className="relative mx-auto max-w-[920px] px-6 pt-16 pb-9 text-center sm:pt-20 lg:pt-24">
          <div className="relative mx-auto max-w-[820px]">
            <div className="ns-stamp mb-7 inline-flex items-center gap-2 rounded-full bg-white/90 px-3 py-1.5">
              <span className="h-1.5 w-1.5 rounded-full bg-[#16a34a]" />
              <span className="mono text-[11px] font-medium text-[#1e40af]">INC-0E7C54F8B5 · CLOSED · 42/42 RECONCILED · VERIFIER PASS</span>
            </div>

            <h1 className="display mx-auto max-w-[15ch] text-[42px] text-[#171717] sm:text-[58px] lg:text-[68px]">
              When the freezer fails, the response is already moving.
            </h1>

            <p className="mx-auto mt-6 max-w-[58ch] text-[17px] leading-relaxed text-[#525252] sm:text-[18px]">
              Night Shift assesses the incident, reserves safe backup capacity, coordinates
              responders, verifies each transfer, and closes only when everything is
              accounted for.
            </p>

            <div className="mt-8 flex flex-wrap items-center justify-center gap-2">
            <Link
              href={headline ? `/app/incidents/${headline.incident_id}` : "/app"}
              className="inline-flex items-center rounded-[8px] bg-black px-5 py-2.5 text-[14px] font-medium text-white shadow-[rgba(0,0,0,0.05)_0px_1px_2px_0px] hover:bg-[#171717]"
            >
              Watch the rescue
            </Link>
            <Link
              href="/app/drills"
              className="inline-flex items-center rounded-[8px] border border-[#e5e5e5] bg-white px-5 py-2.5 text-[14px] font-medium text-[#171717] hover:bg-[#f5f5f5]"
            >
              Explore failure drills
            </Link>
            <Link
              href="/verify"
              className="inline-flex items-center rounded-[8px] px-5 py-2.5 text-[14px] font-medium text-[#171717] hover:bg-[#f5f5f5]"
            >
              Verify the proof
            </Link>
            </div>

            <p className="mx-auto mt-6 max-w-[70ch] text-[12px] text-[#737373]">
              A worker restart replayed one receipt, not one rescue. An unsafe custody move was
              refused. The research estate is synthetic and responder movements are simulated —
              no real biobank samples were moved.
            </p>
          </div>
        </div>

        {/* The console walks itself from estate to signed proof. Each stop stands on its
            own data: gating the whole tour behind a live incident collapsed it to a single
            static frame on any environment that had not run one yet, hiding the fleet,
            drill, and evidence surfaces that need no incident at all. A single posed screenshot
            of an overview page understates the product: the claim is that a rescue travels
            all the way to a verifiable manifest, so the hero travels with it. */}
        <div className="relative mx-auto max-w-[1200px] px-4 pt-7 pb-8 sm:px-6 lg:pt-10 lg:pb-12">
          <ConsoleTour
            footnote="Live data from the deployed API. Hover to hold a screen, or click any step."
            stops={[
              ...(overview
                ? [
                    {
                      id: "overview",
                      label: "Overview",
                      tone: "orange" as const,
                      panel: <PanelEstate overview={overview} />,
                    },
                  ]
                : []),
              ...(overview && headline
                ? [
                    {
                      id: "incident",
                      label: "Incidents",
                      tone: "blue" as const,
                      panel: <MockupBody overview={overview} incident={headline} />,
                    },
                  ]
                : []),
              ...(fleet
                ? [
                    {
                      id: "fleet",
                      label: "Fleet",
                      tone: "blue" as const,
                      panel: <PanelFleet fleet={fleet} />,
                    },
                  ]
                : []),
              ...(drills
                ? [
                    {
                      id: "drills",
                      label: "Drills",
                      tone: "blue" as const,
                      panel: <PanelDrills drills={drills} />,
                    },
                  ]
                : []),
              ...(evidence?.manifests?.length
                ? [
                    {
                      id: "evidence",
                      label: "Evidence",
                      tone: "green" as const,
                      panel: <PanelEvidence evidence={evidence} />,
                    },
                  ]
                : []),
              ...(overview
                ? []
                : [{ id: "preview", label: "Overview", panel: <PreviewFallback /> }]),
            ]}
          />
        </div>
      </section>
      </div>

      {/* Mechanism */}
      <Section
        eyebrow="Mechanism"
        title="From alarm to reconciled custody"
        body="Existing monitoring tells a lab that something is wrong. Night Shift owns everything that has to happen next."
      >
        <figure className="mb-4 overflow-hidden rounded-[12px] border border-[#dbeafe] bg-[#fbfdff] px-4 py-5 sm:px-7">
          <Image
            src="/brand/response-line.webp"
            sizes="(max-width: 640px) 100vw, 1040px"
            alt="A visual route from a detected freezer event to a verified response."
            width={2079}
            height={756}
            className="mx-auto h-auto w-full max-w-[1040px]"
          />
          <figcaption className="mt-3 border-t border-[#dbeafe] pt-3 text-[12px] text-[#525252]">
            A response is a controlled route: detect, contain, reserve, dispatch, verify, reconcile.
          </figcaption>
        </figure>
        <div className="grid gap-0 overflow-hidden rounded-[12px] border border-[#e5e5e5] sm:grid-cols-2 lg:grid-cols-3">
          {[
            ["Assess", "Temperature history and door events separate a door excursion from a failing compressor. A transient event does not trigger a rescue."],
            ["Contain", "A containment hold freezes normal placement and withdrawal on the failed unit, so material cannot move in behind the rescue."],
            ["Reserve", "Backup capacity is reserved inside a database transaction. Two incidents racing for the last slots cannot both win."],
            ["Dispatch", "A work order opens and an on-call responder is dispatched. Retrying either one returns the original receipt, not a second truck roll."],
            ["Verify", "Custody commits only when the container belongs to the incident, a reservation covers the destination, both scans exist, and the destination is cold and freshly read."],
            ["Close", "Closure is refused while any container is unresolved, any effect is uncertain, or containment has not been released against a validated recovery."],
          ].map(([title, body], index) => (
            <div key={title} className="group relative border-r border-b border-[#e5e5e5] bg-white p-5 last:border-b-0 sm:nth-[2n]:border-r-0 lg:nth-[2n]:border-r lg:nth-[3n]:border-r-0 lg:nth-last-[n+1]:border-b-0">
              <span className="mono text-[11px] text-[#2563eb]">0{index + 1}</span>
              <h3 className="text-[14px] font-semibold text-[#171717]">{title}</h3>
              <p className="mt-1.5 text-[13px] leading-relaxed text-[#525252]">{body}</p>
              <span className="mt-4 block h-px w-8 bg-[#2563eb] transition-all group-hover:w-14" />
            </div>
          ))}
        </div>
      </Section>

      {/* Authority */}
      <Section
        eyebrow="Trust"
        title="Agents decide what to do. Deterministic code decides what is true."
        body="Gemini interprets noisy telemetry, prioritises material, and chooses among valid options. It is never the authority on whether capacity exists, whether an effect already happened, or whether custody may change."
        alt
      >
        <div className="grid gap-3 lg:grid-cols-[0.8fr_1.2fr]">
          <figure className="relative min-h-[270px] overflow-hidden rounded-[12px] border border-[#dbeafe] bg-white p-5">
            <Image
              src="/brand/authority-boundary.webp"
              sizes="(max-width: 1024px) 100vw, 520px"
              alt="Illustration of a protected authority boundary with approved and denied paths."
              width={1536}
              height={1024}
              className="absolute top-1/2 left-1/2 w-[115%] max-w-none -translate-x-1/2 -translate-y-1/2"
            />
            <figcaption className="relative mt-auto pt-[205px] text-[12px] text-[#525252]">
              Every route enters through a narrow, policy-checked boundary.
            </figcaption>
          </figure>
          <div className="grid gap-3">
            <Card>
              <h3 className="text-[14px] font-semibold text-[#171717]">
                Six specialists, six authority boundaries
              </h3>
              <p className="mt-1.5 text-[13px] leading-relaxed text-[#525252]">
                Each agent runs under its own identity with its own tool set. The Dispatch
                Agent holds no inventory authority at all, so a poisoned vendor reply asking
                it to export the specimen list has nothing to reach. The Commander cannot
                reserve capacity, open work orders, or move material — a compromised
                Commander can request a plan change and nothing else.
              </p>
              <Link
                href="/app/fleet"
                className="mt-3 inline-block text-[13px] font-medium text-[#2563eb] hover:underline"
              >
                See the permission matrix →
              </Link>
            </Card>
            <Card>
              <h3 className="text-[14px] font-semibold text-[#171717]">
                Thirteen invariants, checked twice
              </h3>
              <p className="mt-1.5 text-[13px] leading-relaxed text-[#525252]">
                Capacity conservation, exactly-once effects, custody prerequisites,
                destination freshness, complete reconciliation, no premature close. The
                production services check them before committing, and the offline verifier
                recomputes them from the stored snapshot afterwards — with no model
                involved.
              </p>
              <Link
                href="/verify"
                className="mt-3 inline-block text-[13px] font-medium text-[#2563eb] hover:underline"
              >
                Verify a manifest yourself →
              </Link>
            </Card>
          </div>
        </div>
      </Section>

      {/* Measured results */}
      <Section
        eyebrow="Qualification"
        title="No revision gets authority because it built"
        body="Every candidate revision runs a disaster drill corpus with faults injected at tool boundaries. The verdict is computed by deterministic Python over stored artifacts — an LLM may explain a failure, never change it."
      >
        {scripted ? (
          <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
            <Stat
              value={`${scripted.passed}/${scripted.scored_runs}`}
              label="drill runs passed"
              hint="deterministic tier"
            />
            <Stat
              value={String(scripted.capacity_overbooking_violations)}
              label="overbooking violations"
              hint="observed across the run set"
              good={scripted.capacity_overbooking_violations === 0}
            />
            <Stat
              value={String(scripted.runs_with_duplicate_effect_after_fault)}
              label="duplicate effects"
              hint={`under ${scripted.faults_injected_total} injected faults`}
              good={scripted.runs_with_duplicate_effect_after_fault === 0}
            />
            <Stat
              value={String(scripted.authorization_denials_total)}
              label="authorization denials"
              hint="forbidden tool attempts refused"
            />
          </div>
        ) : (
          <Card>
            <p className="text-[13px] text-[#737373]">
              No campaign results have been generated yet. Run{" "}
              <Mono>make evidence</Mono> to produce them.
            </p>
          </Card>
        )}
        {agent ? (
          <p className="mt-3 text-[12px] text-[#737373]">
            A separate live-agent tier ran {agent.scored_runs} drill
            {agent.scored_runs === 1 ? "" : "s"} against the real Gemini fleet, passing{" "}
            {agent.passed}. The two tiers are reported separately and never pooled.
          </p>
        ) : null}
        <div className="mt-4">
          <Link
            href="/app/drills"
            className="text-[13px] font-medium text-[#2563eb] hover:underline"
          >
            Every drill, every expectation, every result →
          </Link>
        </div>
      </Section>

      {/* Proof */}
      <Section
        eyebrow="Proof"
        title="Every completed incident ships a signed manifest"
        body="Canonical JSON, hashed with SHA-256, signed with a Cloud KMS asymmetric key. The manifest carries the full state snapshot, so a verifier rebuilds the world and recomputes the verdict rather than taking ours."
        alt
      >
        <figure className="mb-4 overflow-hidden rounded-[12px] border border-[#dbeafe] bg-[#fbfdff] px-3 py-4 sm:px-6">
          <Image
            src="/brand/verified-route.webp"
            sizes="(max-width: 1024px) 100vw, 1100px"
            alt="A visual map of multiple response paths converging on a verified completion."
            width={1586}
            height={992}
            className="h-auto w-full"
          />
          <figcaption className="px-2 pt-2 text-[12px] text-[#525252]">
            Every path ends in a checked, signed state—not an assertion in a dashboard.
          </figcaption>
        </figure>
        <Card padded={false}>
          <div className="border-b border-[#e5e5e5] px-4 py-3">
            <h3 className="text-[14px] font-semibold text-[#171717]">
              Verify without trusting us
            </h3>
          </div>
          <div className="p-4">
            <pre className="mono scroll-x rounded-[8px] border border-[#e5e5e5] bg-[#f5f5f5] px-3 py-2.5 text-[12px] text-[#171717]">
              python -m nightshift.verify --manifest evidence/incidents/&lt;id&gt;.manifest.json
            </pre>
            <p className="mt-3 text-[13px] leading-relaxed text-[#525252]">
              Needs no model, no network, and no Google Cloud credentials. Tampering with
              the state snapshot, the stored verdict, or the signature each produce a
              distinct <Mono>MISMATCH</Mono>. An unsigned manifest reports{" "}
              <Mono>PARTIAL</Mono>, never <Mono>PASS</Mono>.
            </p>
            {evidence?.manifests?.length ? (
              <div className="mt-4 flex flex-wrap gap-2">
                {evidence.manifests.slice(0, 4).map((m) => (
                  <Link
                    key={m.incident_id}
                    href={`/proof/${m.incident_id}`}
                    className="inline-flex items-center gap-2 rounded-full border border-[#e5e5e5] px-3 py-1 text-[12px] hover:bg-[#f5f5f5]"
                  >
                    <Mono>{m.incident_id}</Mono>
                    <Badge tone={m.verification_status === "PASS" ? "green" : "orange"}>
                      {m.verification_status}
                    </Badge>
                  </Link>
                ))}
              </div>
            ) : null}
          </div>
        </Card>
      </Section>

      {/* Cloud */}
      <Section
        eyebrow="Google Cloud"
        title="Running live, not described"
        body="Gemini 3.5 Flash on Vertex AI drives six ADK specialists. Six domain services run on Cloud Run, each under its own service account, with Firestore transactions enforcing capacity conservation and Cloud KMS signing the evidence."
      >
        <div className="scroll-x">
          <div className="flex min-w-[640px] flex-wrap gap-2">
            {[
              "Gemini 3.5 Flash",
              "Google ADK",
              "Cloud Run",
              "Firestore",
              "Pub/Sub",
              "Cloud KMS",
              "Cloud Storage",
              "Model Armor",
              "Agent Registry",
              "Agent Identity",
              "Cloud Trace",
            ].map((name) => (
              <span
                key={name}
                className="rounded-full border border-[#e5e5e5] px-3 py-1.5 text-[13px] text-[#404040]"
              >
                {name}
              </span>
            ))}
          </div>
        </div>
      </Section>

      <footer className="bg-[#f5f5f5] px-3 py-3 sm:px-6 sm:py-6 lg:px-10 lg:py-10">
        <div className="mx-auto max-w-[1420px] overflow-hidden rounded-[24px] border border-[#d4d4d4] bg-white">
          <section className="relative overflow-hidden bg-[#080808] px-6 py-14 text-center text-white sm:px-10 sm:py-18">
            <Image
              src="/brand/response-line.webp"
              sizes="(max-width: 640px) 100vw, 1040px"
              alt=""
              width={2079}
              height={756}
              className="pointer-events-none absolute top-1/2 left-1/2 w-[1050px] max-w-none -translate-x-1/2 -translate-y-1/2 opacity-25 grayscale invert"
            />
            <div className="relative mx-auto max-w-[620px]">
              <p className="mono text-[11px] tracking-[0.12em] text-[#93c5fd] uppercase">Ready for the next alarm</p>
              <h2 className="display mt-3 text-[38px] sm:text-[48px]">See what a controlled rescue looks like.</h2>
              <p className="mt-4 text-[16px] leading-relaxed text-[#a3a3a3]">
                Follow a completed incident from the first reading to independently verified closure.
              </p>
              <div className="mt-7 flex flex-wrap justify-center gap-2">
                <Link href={headline ? `/app/incidents/${headline.incident_id}` : "/app"} className="rounded-[8px] bg-white px-5 py-2.5 text-[14px] font-medium text-[#171717] hover:bg-[#e5e5e5]">
                  Open the command console
                </Link>
                <Link href="/verify" className="rounded-[8px] border border-white/25 px-5 py-2.5 text-[14px] font-medium text-white hover:bg-white/10">
                  Verify the evidence
                </Link>
              </div>
            </div>
          </section>
          <div className="mx-3 my-3 grid gap-8 rounded-[20px] border border-[#e5e5e5] px-6 py-9 sm:mx-6 sm:px-10 md:grid-cols-[1.2fr_0.8fr_0.8fr]">
          <div>
            <Logo size={14} />
            <p className="mt-3 max-w-[34ch] text-[13px] leading-relaxed text-[#525252]">
              A controlled response layer for research-freezer incidents—from first alarm to reconciled custody.
            </p>
          </div>
          <div>
            <p className="ns-eyebrow">Product</p>
            <div className="mt-3 flex flex-col items-start gap-2 text-[13px] font-medium text-[#404040]">
              <Link href="/app/incidents" className="hover:text-[#2563eb]">Live incidents</Link>
              <Link href="/app/fleet" className="hover:text-[#2563eb]">Authority map</Link>
              <Link href="/app/drills" className="hover:text-[#2563eb]">Failure drills</Link>
            </div>
          </div>
          <div>
            <p className="ns-eyebrow">Proof</p>
            <div className="mt-3 flex flex-col items-start gap-2 text-[13px] font-medium text-[#404040]">
              <Link href="/verify" className="hover:text-[#2563eb]">Verify manifests</Link>
              <Link href="/app/evidence" className="hover:text-[#2563eb]">Claim ledger</Link>
              <a href="https://github.com/winsznx/night-shift" className="hover:text-[#2563eb]">Source repository</a>
            </div>
          </div>
          </div>
          <div className="border-t border-[#e5e5e5]">
          <div className="flex flex-wrap items-center justify-between gap-3 px-6 py-4 sm:px-10">
            <p className="text-[11px] text-[#737373]">Synthetic research estate · simulated field events · built for the All Things Agentic Hackathon</p>
            <p className="mono text-[10px] text-[#737373]">US-CENTRAL1 / PROOF-CARRYING RESPONSE</p>
          </div>
        </div>
        </div>
      </footer>
    </div>
  );
}

function Nav() {
  return (
    <header className="relative z-10 px-3 pt-3 sm:px-5 sm:pt-5">
      <div className="mx-auto flex max-w-[1280px] items-center justify-between gap-3 rounded-[14px] border border-[#e5e5e5] bg-white/95 px-3 py-2.5 shadow-[0_8px_20px_rgba(10,10,10,0.06)] backdrop-blur sm:px-4">
        <Logo />
        <nav className="hidden items-center gap-1 md:flex">
          {[
            ["/app", "Product"],
            ["/app/fleet", "Fleet"],
            ["/app/drills", "Drills"],
            ["/app/evidence", "Evidence"],
          ].map(([href, label]) => (
            <Link
              key={href}
              href={href}
              className="rounded-full px-4 py-1.5 text-[14px] text-[#171717] hover:bg-[#f5f5f5]"
            >
              {label}
            </Link>
          ))}
        </nav>
        <div className="flex items-center gap-2">
          <Link
            href="/verify"
            className="hidden rounded-[8px] border border-[#e5e5e5] bg-white px-4 py-1.5 text-[14px] font-medium text-[#171717] hover:bg-[#f5f5f5] sm:inline-flex"
          >
            Verify
          </Link>
          <Link
            href="/app"
            className="rounded-[8px] bg-black px-4 py-1.5 text-[14px] font-medium text-white hover:bg-[#171717]"
          >
            Open console
          </Link>
          <details className="relative md:hidden">
            <summary className="cursor-pointer list-none rounded-[8px] border border-[#e5e5e5] px-3 py-1.5 text-[14px] font-medium text-[#171717] hover:bg-[#f5f5f5] [&::-webkit-details-marker]:hidden">
              Menu
            </summary>
            <nav className="absolute top-[calc(100%+8px)] right-0 grid w-[190px] gap-1 rounded-[12px] border border-[#e5e5e5] bg-white p-2 shadow-[0_12px_32px_rgba(10,10,10,0.12)]">
              {[["/app", "Product"], ["/app/fleet", "Fleet"], ["/app/drills", "Drills"], ["/app/evidence", "Evidence"], ["/verify", "Verify"]].map(([href, label]) => (
                <Link key={href} href={href} className="rounded-[8px] px-3 py-2 text-[14px] text-[#171717] hover:bg-[#f5f5f5]">
                  {label}
                </Link>
              ))}
            </nav>
          </details>
        </div>
      </div>
    </header>
  );
}

function Pill({ color, label }: { color: string; label: string }) {
  return (
    <span className="inline-flex items-center gap-2 rounded-full px-4 py-2 text-[14px] font-medium text-[#171717]">
      <span className="h-2 w-2 rounded-full" style={{ background: color }} aria-hidden />
      {label}
    </span>
  );
}

function MockupHeader() {
  return (
    <div className="flex items-center gap-2 border-b border-[#e5e5e5] bg-[#f5f5f5] px-4 py-2.5">
      <div className="flex gap-1.5" aria-hidden>
        <span className="h-2.5 w-2.5 rounded-full bg-[#d4d4d4]" />
        <span className="h-2.5 w-2.5 rounded-full bg-[#d4d4d4]" />
        <span className="h-2.5 w-2.5 rounded-full bg-[#d4d4d4]" />
      </div>
      <span className="mono ml-2 text-[11px] text-[#737373]">
        night-shift · incident command
      </span>
    </div>
  );
}

function MockupRail() {
  const items = ["Overview", "Incidents", "Freezers", "Capacity", "Fleet", "Drills", "Evidence"];
  return (
    <aside className="hidden border-r border-[#e5e5e5] bg-[#fafafa] p-3 lg:block">
      <p className="mono px-2 pb-3 text-[10px] tracking-[0.1em] text-[#737373] uppercase">Operations</p>
      <nav className="space-y-1" aria-label="Command console preview navigation">
        {items.map((item, index) => (
          <span
            key={item}
            className={`flex items-center gap-2 rounded-[7px] px-2.5 py-2 text-[12px] ${index === 0 ? "bg-[#dbeafe] font-medium text-[#171717]" : "text-[#525252]"}`}
          >
            <span className={`h-1.5 w-1.5 rounded-full ${index === 1 ? "bg-[#ea580c]" : index === 0 ? "bg-[#2563eb]" : "bg-[#d4d4d4]"}`} />
            {item}
          </span>
        ))}
      </nav>
      <div className="mt-8 rounded-[8px] border border-[#dbeafe] bg-white p-2.5">
        <p className="mono text-[9px] text-[#1e40af]">RUN STATE</p>
        <p className="mt-1 text-[11px] font-medium text-[#171717]">Evidence attached</p>
      </div>
    </aside>
  );
}

/** The public page must remain communicative when the live API is unavailable. This is
 * deliberately labelled as a reference scenario, never presented as current telemetry. */
function PreviewFallback() {
  return (
    <div className="grid gap-0 md:grid-cols-[1fr_260px]">
      <div className="border-b border-[#e5e5e5] p-5 md:border-r md:border-b-0 lg:p-6">
        <div className="flex flex-wrap items-start justify-between gap-3 border-b border-[#e5e5e5] pb-4">
          <div>
            <p className="mono text-[10px] tracking-[0.1em] text-[#737373] uppercase">Reference command preview</p>
            <h3 className="mt-1 text-[18px] font-semibold tracking-[-0.02em] text-[#171717]">A completed freezer response</h3>
          </div>
          <Badge tone="green" dot>closed</Badge>
        </div>
        <div className="mt-5 grid grid-cols-2 gap-5 sm:grid-cols-4">
          <MockStat label="Freezer" value="FZ-04" hint="recovered" />
          <MockStat label="Impacted" value="42" hint="containers" />
          <MockStat label="Committed" value="42" hint="custody" />
          <MockStat label="Unresolved" value="0" hint="reconciled" />
        </div>
        <div className="mt-7 rounded-[10px] border border-[#e5e5e5] bg-[#fafafa] p-4">
          <div className="flex items-center justify-between gap-3">
            <p className="text-[13px] font-medium text-[#171717]">Closure conditions</p>
            <span className="mono text-[11px] text-[#16a34a]">13 / 13 checked</span>
          </div>
          <div className="mt-4 grid gap-2 sm:grid-cols-3">
            {[
              ["Capacity", "reserved then released"],
              ["Custody", "all scans committed"],
              ["Evidence", "manifest verified"],
            ].map(([label, value]) => (
              <div key={label} className="rounded-[8px] border border-[#e5e5e5] bg-white p-3">
                <p className="mono text-[10px] text-[#737373] uppercase">{label}</p>
                <p className="mt-1 text-[12px] font-medium text-[#171717]">{value}</p>
              </div>
            ))}
          </div>
        </div>
      </div>
      <aside className="p-5">
        <p className="mono text-[10px] tracking-[0.1em] text-[#737373] uppercase">Response record</p>
        <div className="mt-3 space-y-3">
          {[
            ["01", "Alarm assessed", "sustained warming confirmed"],
            ["02", "Backup reserved", "capacity held once"],
            ["03", "Custody reconciled", "42 container receipts"],
            ["04", "Manifest signed", "independent verifier pass"],
          ].map(([step, title, body]) => (
            <div key={step} className="ns-route pl-3">
              <p className="mono text-[10px] text-[#2563eb]">{step}</p>
              <p className="text-[12px] font-medium text-[#171717]">{title}</p>
              <p className="text-[11px] leading-snug text-[#737373]">{body}</p>
            </div>
          ))}
        </div>
        <p className="mt-5 text-[11px] leading-snug text-[#737373]">Reference scenario shown while live telemetry is unavailable.</p>
      </aside>
    </div>
  );
}

function MockupBody({
  overview,
  incident,
}: {
  overview: NonNullable<Awaited<ReturnType<typeof getOverview>>>;
  incident: NonNullable<Awaited<ReturnType<typeof getOverview>>>["incidents"][number];
}) {
  const failed = overview.freezers.find((f) => f.freezer_id === incident.failed_freezer_id);
  return (
    <div className="grid gap-0 md:grid-cols-[1fr_260px]">
      <div className="border-b border-[#e5e5e5] p-5 md:border-r md:border-b-0 lg:p-6">
        <div className="mb-5 flex flex-wrap items-start justify-between gap-3 border-b border-[#e5e5e5] pb-4">
          <div>
            <p className="mono text-[10px] tracking-[0.1em] text-[#737373] uppercase">Incident command</p>
            <h3 className="mt-1 text-[18px] font-semibold tracking-[-0.02em] text-[#171717]">Response overview</h3>
          </div>
          <span className="rounded-full border border-[#e5e5e5] bg-white px-2.5 py-1 text-[11px] text-[#525252]">Live state</span>
        </div>
        <div className="flex flex-wrap items-center gap-2">
          <Mono className="text-[13px] font-medium text-[#171717]">
            {incident.incident_id}
          </Mono>
          <Badge tone={incident.state === "CLOSED" ? "green" : "blue"} dot>
            {incident.state.replace(/_/g, " ")}
          </Badge>
          <Badge tone="orange">{incident.severity}</Badge>
        </div>

        <div className="mt-5 grid grid-cols-2 gap-5 sm:grid-cols-4">
          <MockStat
            label="Freezer"
            value={incident.failed_freezer_id}
            hint={failed ? `${failed.current_temp_c.toFixed(1)}°C` : undefined}
          />
          <MockStat label="Impacted" value={String(incident.impacted_containers)} hint="containers" />
          <MockStat label="Committed" value={String(incident.committed)} hint="custody" />
          <MockStat
            label="Unresolved"
            value={String(incident.unresolved)}
            hint={incident.complete ? "reconciled" : "outstanding"}
            bad={incident.unresolved > 0}
          />
        </div>

        {failed ? <TempTrace freezer={failed} /> : null}
      </div>

      <div className="p-5">
        <p className="text-[11px] font-medium tracking-wide text-[#737373] uppercase">
          Backup capacity
        </p>
        <ul className="mt-3 space-y-2">
          {overview.freezers
            .filter((f) => f.is_backup_qualified)
            .slice(0, 5)
            .map((f) => (
              <li key={f.freezer_id} className="flex items-center justify-between gap-2">
                <Mono className="text-[12px] text-[#171717]">{f.freezer_id}</Mono>
                <span className="flex items-center gap-2">
                  <span className="mono text-[12px] text-[#525252]">
                    {f.current_temp_c.toFixed(1)}°C
                  </span>
                  <span className="mono text-[12px] font-medium text-[#171717]">
                    {f.free_slots}
                  </span>
                </span>
              </li>
            ))}
        </ul>
      </div>
    </div>
  );
}

function MockStat({
  label,
  value,
  hint,
  bad,
}: {
  label: string;
  value: string;
  hint?: string;
  bad?: boolean;
}) {
  return (
    <div>
      <div className="text-[11px] tracking-wide text-[#737373] uppercase">{label}</div>
      <div
        className={`mono mt-1 text-[20px] leading-none font-medium ${bad ? "text-[#dc2626]" : "text-[#171717]"}`}
      >
        {value}
      </div>
      {hint ? <div className="mt-1 text-[11px] text-[#737373]">{hint}</div> : null}
    </div>
  );
}

/** A tiny sparkline built from the freezer's own numbers, not a decorative shape. */
function TempTrace({ freezer }: { freezer: { current_temp_c: number; setpoint_c: number; alarm_high_c: number } }) {
  const span = Math.max(1, freezer.alarm_high_c - freezer.setpoint_c);
  const pct = Math.min(
    100,
    Math.max(0, ((freezer.current_temp_c - freezer.setpoint_c) / span) * 100),
  );
  const over = freezer.current_temp_c > freezer.alarm_high_c;
  return (
    <div className="mt-6">
      <div className="flex items-center justify-between text-[11px] text-[#737373]">
        <span className="mono">{freezer.setpoint_c.toFixed(0)}°C setpoint</span>
        <span className="mono">{freezer.alarm_high_c.toFixed(0)}°C alarm</span>
      </div>
      <div className="mt-1.5 h-2 w-full overflow-hidden rounded-full bg-[#f5f5f5]">
        <div
          className="h-full rounded-full transition-all"
          style={{
            width: `${Math.max(3, pct)}%`,
            background: over ? "#dc2626" : pct > 70 ? "#ea580c" : "#2563eb",
          }}
        />
      </div>
      <p className="mt-2 text-[12px] text-[#525252]">
        {over
          ? "Above alarm threshold — sustained warming confirmed."
          : "Holding within alarm threshold."}
      </p>
    </div>
  );
}

function Section({
  eyebrow,
  title,
  body,
  children,
  alt,
}: {
  eyebrow: string;
  title: string;
  body: string;
  children: React.ReactNode;
  alt?: boolean;
}) {
  return (
    <section className={alt ? "border-b border-[#e5e5e5] bg-[#f5f5f5]" : "border-b border-[#e5e5e5]"}>
      <div className="mx-auto max-w-[1200px] px-6 py-16">
        <p className="text-[12px] font-medium tracking-wide text-[#2563eb] uppercase">
          {eyebrow}
        </p>
        <h2 className="mt-2 max-w-[28ch] text-[30px] leading-tight font-semibold text-[#171717]">
          {title}
        </h2>
        <p className="mt-3 max-w-[68ch] text-[16px] leading-relaxed text-[#525252]">{body}</p>
        <div className="mt-8">{children}</div>
      </div>
    </section>
  );
}

function Stat({
  value,
  label,
  hint,
  good,
}: {
  value: string;
  label: string;
  hint?: string;
  good?: boolean;
}) {
  return (
    <Card>
      <div
        className={`mono text-[30px] leading-none font-medium ${good ? "text-[#16a34a]" : "text-[#171717]"}`}
      >
        {value}
      </div>
      <div className="mt-2 text-[13px] font-medium text-[#171717]">{label}</div>
      {hint ? <div className="mt-0.5 text-[12px] text-[#737373]">{hint}</div> : null}
    </Card>
  );
}

/* ---------------------------------------------------------------------------------
 * Console tour panels
 *
 * Each is a real screen rendered from live data. The tour moves between them so the
 * hero shows the whole path from estate to signed proof rather than one dashboard.
 * ------------------------------------------------------------------------------- */

function PanelShell({
  eyebrow,
  title,
  note,
  children,
}: {
  eyebrow: string;
  title: string;
  note?: string;
  children: React.ReactNode;
}) {
  return (
    <div className="p-5 lg:p-6">
      <div className="mb-5 flex flex-wrap items-start justify-between gap-3 border-b border-[#e5e5e5] pb-4">
        <div>
          <p className="mono text-[10px] tracking-[0.1em] text-[#737373] uppercase">{eyebrow}</p>
          <h3 className="mt-1 text-[18px] font-semibold tracking-[-0.02em] text-[#171717]">
            {title}
          </h3>
        </div>
        {note ? (
          <span className="rounded-full border border-[#e5e5e5] bg-white px-2.5 py-1 text-[11px] text-[#525252]">
            {note}
          </span>
        ) : null}
      </div>
      {children}
    </div>
  );
}

function PanelEstate({ overview }: { overview: NonNullable<Awaited<ReturnType<typeof getOverview>>> }) {
  const alarmed = overview.freezers.filter((f) => f.above_alarm);
  return (
    <PanelShell
      eyebrow="Operations"
      title="Freezer estate"
      note={`${overview.active_incidents} active`}
    >
      <div className="mb-5 grid grid-cols-2 gap-5 sm:grid-cols-4">
        <MockStat label="Freezers" value={String(overview.freezers.length)} hint="monitored" />
        <MockStat label="Above alarm" value={String(alarmed.length)} hint="units" bad={alarmed.length > 0} />
        <MockStat label="Incidents" value={String(overview.active_incidents)} hint="active" />
        <MockStat
          label="Backup"
          value={String(overview.freezers.filter((f) => f.is_backup_qualified).length)}
          hint="qualified"
        />
      </div>
      <ul className="divide-y divide-[#e5e5e5] overflow-hidden rounded-[8px] border border-[#e5e5e5]">
        {overview.freezers.slice(0, 5).map((f) => (
          <li key={f.freezer_id} className="flex items-center justify-between gap-3 px-3 py-2">
            <span className="flex min-w-0 items-center gap-2">
              <span
                className="h-1.5 w-1.5 shrink-0 rounded-full"
                style={{ background: f.above_alarm ? "#ea580c" : "#16a34a" }}
              />
              <Mono className="truncate text-[12px] text-[#171717]">{f.freezer_id}</Mono>
              <span className="truncate text-[12px] text-[#737373]">{f.zone}</span>
            </span>
            <span className="mono shrink-0 text-[12px] text-[#525252]">
              {f.current_temp_c.toFixed(1)}°C · {f.free_slots} free
            </span>
          </li>
        ))}
      </ul>
    </PanelShell>
  );
}

function PanelFleet({ fleet }: { fleet: NonNullable<Awaited<ReturnType<typeof getFleet>>> }) {
  return (
    <PanelShell
      eyebrow="Authority"
      title="Who may cause what"
      note={`${fleet.agents.length} specialists`}
    >
      <ul className="divide-y divide-[#e5e5e5] overflow-hidden rounded-[8px] border border-[#e5e5e5]">
        {fleet.agents.slice(0, 6).map((a) => (
          <li key={a.agent} className="flex items-center justify-between gap-3 px-3 py-2">
            <Mono className="truncate text-[12px] text-[#171717]">{a.agent}</Mono>
            <span className="flex shrink-0 items-center gap-2">
              <span className="mono text-[11px] text-[#16a34a]">{a.allowed_tools.length} allowed</span>
              <span className="mono text-[11px] text-[#dc2626]">
                {a.forbidden_tools.length} denied
              </span>
            </span>
          </li>
        ))}
      </ul>
      <p className="mt-3 text-[12px] leading-relaxed text-[#525252]">
        The Dispatch Agent can read vendor repair notes and holds no inventory authority at
        all — even if a vendor note asks it to export the specimen manifest.
      </p>
    </PanelShell>
  );
}

function PanelDrills({ drills }: { drills: NonNullable<Awaited<ReturnType<typeof getDrills>>> }) {
  const scripted = drills.campaign?.by_driver?.scripted;
  return (
    <PanelShell eyebrow="Qualification" title="Disaster drill range" note={`corpus ${drills.corpus_version}`}>
      <div className="mb-5 grid grid-cols-2 gap-5 sm:grid-cols-4">
        <MockStat label="Runs" value={String(scripted?.scored_runs ?? 0)} hint="scored" />
        <MockStat label="Passed" value={String(scripted?.passed ?? 0)} hint="drills" />
        <MockStat
          label="N1"
          value={String(scripted?.capacity_overbooking_violations ?? 0)}
          hint="overbooking"
          bad={(scripted?.capacity_overbooking_violations ?? 0) > 0}
        />
        <MockStat
          label="N2"
          value={String(scripted?.duplicate_effect_violations ?? 0)}
          hint="duplicates"
          bad={(scripted?.duplicate_effect_violations ?? 0) > 0}
        />
      </div>
      <ul className="divide-y divide-[#e5e5e5] overflow-hidden rounded-[8px] border border-[#e5e5e5]">
        {drills.drills.slice(0, 4).map((d) => (
          <li key={d.id} className="flex items-center justify-between gap-3 px-3 py-2">
            <span className="flex min-w-0 items-center gap-2">
              <Mono className="shrink-0 text-[12px] text-[#2563eb]">{d.id}</Mono>
              <span className="truncate text-[12px] text-[#525252]">{d.title}</span>
            </span>
          </li>
        ))}
      </ul>
    </PanelShell>
  );
}

function PanelEvidence({
  evidence,
}: {
  evidence: NonNullable<Awaited<ReturnType<typeof getEvidence>>>;
}) {
  return (
    <PanelShell
      eyebrow="Proof"
      title="Signed incident manifests"
      note={`${evidence.manifests.length} published`}
    >
      <ul className="divide-y divide-[#e5e5e5] overflow-hidden rounded-[8px] border border-[#e5e5e5]">
        {evidence.manifests.slice(0, 4).map((m) => (
          <li key={m.incident_id} className="flex items-center justify-between gap-3 px-3 py-2">
            <span className="flex min-w-0 items-center gap-2">
              <Mono className="truncate text-[12px] text-[#171717]">{m.incident_id}</Mono>
              <span className="text-[11px] text-[#737373]">{m.incident_state}</span>
            </span>
            <span className="flex shrink-0 items-center gap-2">
              <span className="mono text-[11px] text-[#525252]">
                {m.reconciliation.committed.length}/{m.reconciliation.total}
              </span>
              <Badge tone={m.verification_status === "PASS" ? "green" : "orange"} dot>
                {m.verification_status}
              </Badge>
            </span>
          </li>
        ))}
      </ul>
      <p className="mt-3 text-[12px] leading-relaxed text-[#525252]">
        Signed with a Cloud KMS asymmetric key. The verifier rebuilds the world from the
        snapshot and recomputes the verdict rather than trusting ours.
      </p>
    </PanelShell>
  );
}
