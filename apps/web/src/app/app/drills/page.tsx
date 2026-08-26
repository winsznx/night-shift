import Link from "next/link";

import { AppShell, ApiDown, PageHeader } from "@/components/shell";
import { Badge, Card, CardHeader, Metric, Mono, Table, Td } from "@/components/ui";
import { getDrills } from "@/lib/api";

export const revalidate = 30;

export default async function DrillsPage() {
  const drills = await getDrills();

  return (
    <AppShell active="/app/drills">
      <PageHeader
        title="Disaster drill range"
        subtitle="No revision receives operational authority because it built. It receives authority because it survived this corpus, and the verdict is computed by deterministic Python over stored artifacts."
        right={drills ? <Mono>corpus {drills.corpus_version}</Mono> : undefined}
      />

      {!drills ? (
        <ApiDown what="The drill range" />
      ) : (
        <div className="space-y-4">
          {Object.entries(drills.campaign?.by_driver ?? {}).map(([driver, block]) => (
            <Card key={driver} padded={false}>
              <CardHeader
                title={
                  driver === "scripted"
                    ? "Deterministic tier"
                    : "Live agent tier (Gemini fleet)"
                }
                subtitle={
                  driver === "scripted"
                    ? "A fixed policy drives the same broker, services, and kernel with no model in the loop. Wide enough to measure across many seeds."
                    : "The real fleet on Gemini 3.5 Flash. Slower, so a smaller disclosed sample. Never pooled with the deterministic tier."
                }
                right={
                  <Badge tone={block.passed === block.scored_runs ? "green" : "orange"} dot>
                    {block.passed}/{block.scored_runs} passed
                  </Badge>
                }
              />
              <div className="grid grid-cols-2 gap-5 p-4 sm:grid-cols-3 lg:grid-cols-6">
                <Metric label="Runs scored" value={block.scored_runs} hint={`${block.infrastructure_errors} infra error(s)`} />
                <Metric
                  label="Overbooking"
                  value={block.capacity_overbooking_violations}
                  hint="N1 violations"
                  tone={block.capacity_overbooking_violations === 0 ? "good" : "bad"}
                />
                <Metric
                  label="Duplicate effects"
                  value={block.duplicate_effect_violations}
                  hint="N2 violations"
                  tone={block.duplicate_effect_violations === 0 ? "good" : "bad"}
                />
                <Metric
                  label="Premature close"
                  value={block.premature_close_violations}
                  hint="N6 violations"
                  tone={block.premature_close_violations === 0 ? "good" : "bad"}
                />
                <Metric
                  label="Faults injected"
                  value={block.faults_injected_total}
                  hint={`${block.runs_with_injected_faults} run(s)`}
                />
                <Metric
                  label="Denials"
                  value={block.authorization_denials_total}
                  hint="forbidden calls refused"
                />
              </div>
              <div className="border-t border-[#e5e5e5] px-4 py-2.5 text-[12px] text-[#737373]">
                Median run {block.wall_clock_median_s ?? "—"}s · p95 {block.wall_clock_p95_s ?? "—"}s ·{" "}
                {block.containers_committed_total} container custody commits ·{" "}
                {block.duplicate_receipts_returned} receipts replayed instead of duplicated
              </div>
            </Card>
          ))}

          <Card padded={false}>
            <CardHeader
              title="Corpus"
              subtitle="Expectations are written as invariants and observable state, never as scenario IDs — an agent cannot be tuned to pass a specific drill"
            />
            <Table
              headers={["Drill", "Family", "Scenario", "Faults", "Expectations", "Result"]}
              minWidth={940}
            >
              {drills.drills.map((d) => {
                const results = Object.values(d.results ?? {});
                const runs = results.reduce((n, r) => n + r.runs, 0);
                const passed = results.reduce((n, r) => n + r.passed, 0);
                return (
                  <tr key={d.id} className="hover:bg-[#f5f5f5]">
                    <Td>
                      <Link
                        href={`/app/drills/${d.id}`}
                        className="mono text-[13px] font-medium text-[#2563eb] hover:underline"
                      >
                        {d.id}
                      </Link>
                    </Td>
                    <Td>
                      <Badge tone="neutral">{d.family}</Badge>
                    </Td>
                    <Td className="max-w-[360px]">
                      <span className="text-[13px] font-medium text-[#171717]">{d.title}</span>
                    </Td>
                    <Td>
                      {d.faults.length > 0 ? (
                        <Badge tone="orange">{d.faults.length}</Badge>
                      ) : (
                        <span className="text-[#a3a3a3]">—</span>
                      )}
                    </Td>
                    <Td>
                      <Mono>{d.expectations.length}</Mono>
                    </Td>
                    <Td>
                      {runs === 0 ? (
                        <span className="text-[13px] text-[#a3a3a3]">not run</span>
                      ) : (
                        <Badge tone={passed === runs ? "green" : "red"} dot>
                          {passed}/{runs}
                        </Badge>
                      )}
                    </Td>
                  </tr>
                );
              })}
            </Table>
          </Card>

          <Card>
            <h2 className="text-[14px] font-semibold text-[#171717]">Holdout corpus</h2>
            <p className="mt-1.5 max-w-[76ch] text-[13px] leading-relaxed text-[#525252]">
              A small holdout set runs alongside the public corpus and is deliberately not
              exposed through this application. It exists so that qualification cannot be
              achieved by tuning against the drills a candidate can read.
            </p>
          </Card>
        </div>
      )}
    </AppShell>
  );
}
