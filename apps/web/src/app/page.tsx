import Link from "next/link";

import { Logo } from "@/components/shell";
import { Badge, Card, Mono } from "@/components/ui";
import { getDrills, getEvidence, getOverview } from "@/lib/api";

export const revalidate = 30;

export default async function Landing() {
  const [overview, drills, evidence] = await Promise.all([
    getOverview(),
    getDrills(),
    getEvidence(),
  ]);

  const scripted = drills?.campaign?.by_driver?.scripted;
  const agent = drills?.campaign?.by_driver?.agent;
  const headline = overview?.incidents?.[0];

  return (
    <div className="min-h-screen bg-white">
      <Nav />

      {/* Hero. Copy explains the workflow, not the architecture. */}
      <section className="dotgrid border-b border-[#e5e5e5]">
        <div className="mx-auto max-w-[1200px] px-6 pt-16 pb-14 text-center lg:pt-24">
          <div className="mb-7 flex flex-wrap items-center justify-center gap-2">
            <Pill color="#ea580c" label="Containment" />
            <Pill color="#7c3aed" label="Verified capacity" />
            <Pill color="#16a34a" label="Custody proof" />
          </div>

          <h1 className="display mx-auto max-w-[19ch] text-[36px] text-[#171717] sm:text-[48px]">
            When the freezer fails, the response is already moving.
          </h1>

          <p className="mx-auto mt-5 max-w-[62ch] text-[18px] leading-relaxed text-[#525252]">
            Night Shift assesses the incident, reserves safe backup capacity, coordinates
            responders, verifies each transfer, and closes only when everything is
            accounted for.
          </p>

          <div className="mt-8 flex flex-wrap items-center justify-center gap-2">
            <Link
              href={headline ? `/app/incidents/${headline.incident_id}` : "/app"}
              className="inline-flex items-center rounded-[8px] bg-black px-5 py-2.5 text-[14px] font-medium text-white shadow-[rgba(0,0,0,0.05)_0px_1px_2px_0px] hover:bg-[#171717]"
            >
              Open the live incident
            </Link>
            <Link
              href="/app/drills"
              className="inline-flex items-center rounded-[8px] border border-[#e5e5e5] bg-white px-5 py-2.5 text-[14px] font-medium text-[#171717] hover:bg-[#f5f5f5]"
            >
              See the disaster drills
            </Link>
            <Link
              href="/verify"
              className="inline-flex items-center rounded-[8px] px-5 py-2.5 text-[14px] font-medium text-[#171717] hover:bg-[#f5f5f5]"
            >
              Verify the evidence
            </Link>
          </div>

          <p className="mt-6 text-[12px] text-[#737373]">
            Synthetic research estate. Simulated responder movements. No real biobank
            samples were moved.
          </p>
        </div>

        {/* Product mockup: the real incident, not a picture of one. */}
        <div className="mx-auto max-w-[1200px] px-6 pb-16">
          <div className="overflow-hidden rounded-t-[16px] border border-[#e5e5e5] bg-white shadow-[rgba(0,0,0,0.1)_0px_0px_0px_4px]">
            <MockupHeader />
            {overview && headline ? (
              <MockupBody overview={overview} incident={headline} />
            ) : (
              <div className="px-5 py-14 text-center text-[14px] text-[#737373]">
                No incident data available from the API right now.
              </div>
            )}
          </div>
        </div>
      </section>

      {/* Mechanism */}
      <Section
        eyebrow="Mechanism"
        title="From alarm to reconciled custody"
        body="Existing monitoring tells a lab that something is wrong. Night Shift owns everything that has to happen next."
      >
        <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-3">
          {[
            ["Assess", "Temperature history and door events separate a door excursion from a failing compressor. A transient event does not trigger a rescue."],
            ["Contain", "A containment hold freezes normal placement and withdrawal on the failed unit, so material cannot move in behind the rescue."],
            ["Reserve", "Backup capacity is reserved inside a database transaction. Two incidents racing for the last slots cannot both win."],
            ["Dispatch", "A work order opens and an on-call responder is dispatched. Retrying either one returns the original receipt, not a second truck roll."],
            ["Verify", "Custody commits only when the container belongs to the incident, a reservation covers the destination, both scans exist, and the destination is cold and freshly read."],
            ["Close", "Closure is refused while any container is unresolved, any effect is uncertain, or containment has not been released against a validated recovery."],
          ].map(([title, body]) => (
            <Card key={title}>
              <h3 className="text-[14px] font-semibold text-[#171717]">{title}</h3>
              <p className="mt-1.5 text-[13px] leading-relaxed text-[#525252]">{body}</p>
            </Card>
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
        <div className="grid gap-3 lg:grid-cols-2">
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

      <footer className="border-t border-[#e5e5e5]">
        <div className="mx-auto flex max-w-[1200px] flex-wrap items-center justify-between gap-3 px-6 py-8">
          <Logo size={13} />
          <p className="text-[12px] text-[#737373]">
            Synthetic research estate · simulated field events · built for the All Things
            Agentic hackathon
          </p>
        </div>
      </footer>
    </div>
  );
}

function Nav() {
  return (
    <header className="border-b border-[#e5e5e5]">
      <div className="mx-auto flex max-w-[1200px] items-center justify-between gap-4 px-6 py-3.5">
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
            className="rounded-[8px] border border-[#e5e5e5] bg-white px-4 py-1.5 text-[14px] font-medium text-[#171717] hover:bg-[#f5f5f5]"
          >
            Verify
          </Link>
          <Link
            href="/app"
            className="rounded-[8px] bg-black px-4 py-1.5 text-[14px] font-medium text-white hover:bg-[#171717]"
          >
            Open console
          </Link>
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
      <div className="border-b border-[#e5e5e5] p-5 md:border-r md:border-b-0">
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
