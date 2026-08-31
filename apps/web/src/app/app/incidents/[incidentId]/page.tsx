import Link from "next/link";
import { notFound } from "next/navigation";

import { TemperatureChart } from "@/components/temp-chart";
import { Timeline } from "@/components/timeline";
import { AppShell, PageHeader } from "@/components/shell";
import {
  Badge,
  Card,
  CardHeader,
  Empty,
  InvariantRow,
  Metric,
  Mono,
  StateBadge,
  Table,
  Td,
  custodyTone,
  timeAgo,
} from "@/components/ui";
import { getIncident, getTimeline } from "@/lib/api";

export const dynamic = "force-dynamic";

/**
 * N4 asks how old a telemetry reading is at some instant, and which instant that is
 * changes the answer. The API picks it and says why; the panel has to repeat both or it
 * reads as a live sensor check on an incident that stopped moving days ago.
 */
const EVALUATION_BASIS: Record<string, string> = {
  "incident closed_at":
    "This incident is terminal, so the invariants were asked about the moment it closed. Asking about now would keep ageing evidence that stopped changing, and every settled incident would drift into a failing freshness check and stay there.",
  "sealed manifest evaluated_at":
    "This incident is terminal with no recorded close time, so the instant sealed into its published manifest was used. The offline verifier asks the same question against the same instant.",
  "wall clock":
    "This rescue is still running, so the invariants were asked about right now. A stale telemetry reading here is a live finding.",
};

/**
 * Transcribed from evidence/traces.json, which scripts/verify_traces.py wrote by reading
 * the Cloud Trace API back. The console link below only opens for someone holding IAM on
 * the project, so the numbers it would show belong on the page instead of behind it.
 */
const RECORDED_TRACES = {
  generated_at: "2026-08-26T12:25:33.392Z",
  window_hours: 4,
  traces_examined: 118,
  nightshift_traces: 25,
  total_spans: 496,
  distinct_span_names: 44,
  top_spans: [
    { name: "tool.get_incident", count: 45 },
    { name: "tool.record_pickup", count: 42 },
    { name: "effect.custody_pickup", count: 42 },
    { name: "tool.record_destination_scan", count: 42 },
    { name: "effect.custody_destination_scan", count: 42 },
    { name: "effect.custody_commit", count: 42 },
    { name: "invocation", count: 39 },
    { name: "tool.get_incident_timeline", count: 33 },
    { name: "tool.request_incident_transition", count: 29 },
    { name: "effect.incident_transition", count: 28 },
    { name: "effect.release_hold", count: 21 },
  ],
};

export default async function IncidentDetail({
  params,
}: {
  params: Promise<{ incidentId: string }>;
}) {
  const { incidentId } = await params;
  const [result, timeline] = await Promise.all([
    getIncident(incidentId),
    getTimeline(incidentId),
  ]);
  if (result.missing) notFound();
  // An API that fell over is not an incident that never existed, and saying otherwise
  // here is exactly the claim this product refuses to make. error.tsx takes it from here.
  if (!result.data) {
    throw result.failure ?? new Error(`Incident ${incidentId} could not be loaded.`);
  }
  const detail = result.data;

  const { incident, reconciliation: recon, freezer, invariants } = detail;
  const failedInvariants = invariants.filter((i) => !i.holds);
  const refusals = detail.receipts.filter((r) => r.status === "REFUSED");
  const duplicates = detail.receipts.filter((r) => r.duplicate_returned);
  const liveReservations = detail.reservations.filter((r) =>
    ["ACTIVE", "CONSUMED"].includes(r.state),
  );

  return (
    <AppShell active="/app/incidents">
      <PageHeader
        title={incident.id}
        subtitle={`${incident.failed_freezer_id} · opened ${timeAgo(incident.opened_at, detail.evaluated_at)}`}
        right={
          <>
            <StateBadge state={incident.state} />
            <Badge tone={incident.severity === "SEV1" ? "red" : "orange"}>
              {incident.severity}
            </Badge>
            <Link
              href={`/proof/${incident.id}`}
              className="rounded-[8px] border border-[#e5e5e5] bg-white px-3 py-1.5 text-[13px] font-medium text-[#171717] hover:bg-[#f5f5f5]"
            >
              Proof
            </Link>
          </>
        }
      />

      {/* The headline row: what a responder needs in the first two seconds. */}
      <Card padded={false} className="mb-4">
        <div className="grid grid-cols-2 gap-5 p-4 sm:grid-cols-3 lg:grid-cols-6">
          <Metric
            label="Freezer temp"
            value={freezer ? `${freezer.current_temp_c.toFixed(1)}°C` : "—"}
            hint={freezer ? `alarm ${freezer.alarm_high_c.toFixed(0)}°C` : undefined}
            tone={freezer?.above_alarm ? "bad" : "good"}
          />
          <Metric
            label="Impacted"
            value={recon.total}
            hint={
              detail.impact
                ? `${detail.impact.specimen_total.toLocaleString()} specimens`
                : "no snapshot"
            }
          />
          <Metric
            label="Committed"
            value={recon.committed.length}
            hint="custody transferred"
            tone={recon.committed.length > 0 ? "good" : "default"}
          />
          <Metric
            label="In flight"
            value={recon.in_flight.length}
            hint="picked up, not committed"
            tone={recon.in_flight.length > 0 ? "warn" : "default"}
          />
          <Metric
            label="Unresolved"
            value={recon.unresolved.length}
            hint={recon.complete ? "fully reconciled" : "blocks closure"}
            tone={recon.unresolved.length > 0 ? "bad" : "good"}
          />
          <Metric
            label="Reserved slots"
            value={liveReservations.reduce((n, r) => n + (r.slots_remaining ?? r.slots), 0)}
            hint={`${liveReservations.length} reservation(s)`}
          />
        </div>
      </Card>

      {failedInvariants.length > 0 ? (
        <div className="mb-4 rounded-[12px] border border-[#fecaca] bg-[#fef2f2] p-4">
          <p className="text-[14px] font-semibold text-[#991b1b]">
            {failedInvariants.length} hard invariant
            {failedInvariants.length === 1 ? "" : "s"} not holding
          </p>
          <ul className="mt-1.5 space-y-0.5">
            {failedInvariants.map((i) => (
              <li key={i.invariant} className="text-[13px] text-[#991b1b]">
                <Mono className="text-[#991b1b]">{i.invariant}</Mono> {i.title} · {i.detail}
              </li>
            ))}
          </ul>
        </div>
      ) : null}

      <div className="grid gap-4 xl:grid-cols-[1.5fr_1fr]">
        <div className="min-w-0 space-y-4">
          <Card padded={false}>
            <CardHeader
              title={`${incident.failed_freezer_id} temperature`}
              subtitle="Authoritative sensor readings"
              right={
                freezer ? (
                  <Badge tone={freezer.above_alarm ? "red" : "green"} dot>
                    {freezer.state}
                  </Badge>
                ) : null
              }
            />
            <div className="p-4">
              {freezer ? (
                <TemperatureChart
                  readings={detail.temperature_series}
                  setpoint={freezer.setpoint_c}
                  alarmHigh={freezer.alarm_high_c}
                />
              ) : (
                <Empty title="No freezer record" body="Telemetry is unavailable." />
              )}
            </div>
          </Card>

          <Card padded={false}>
            <CardHeader
              title="Rescue plan"
              subtitle="Reserved destinations and dispatched responders"
            />
            {liveReservations.length === 0 && detail.dispatches.length === 0 ? (
              <Empty
                title="No plan committed yet"
                body="Capacity has not been reserved and no responder has been dispatched."
              />
            ) : (
              <div className="divide-y divide-[#e5e5e5]">
                {liveReservations.length > 0 ? (
                  <Table headers={["Reservation", "Destination", "Group", "Slots", "State"]} minWidth={620}>
                    {liveReservations.map((r) => (
                      <tr key={r.id}>
                        <Td>
                          <Mono>{r.id}</Mono>
                        </Td>
                        <Td>
                          <Mono className="font-medium text-[#171717]">
                            {r.destination_freezer_id}
                          </Mono>
                        </Td>
                        <Td>
                          <Mono className="text-[11px]">{r.placement_group_id}</Mono>
                        </Td>
                        <Td>
                          <Mono>
                            {r.slots_remaining ?? r.slots}/{r.slots}
                          </Mono>
                        </Td>
                        <Td>
                          <Badge tone={r.state === "CONSUMED" ? "green" : "blue"}>
                            {r.state}
                          </Badge>
                        </Td>
                      </tr>
                    ))}
                  </Table>
                ) : null}
                {detail.dispatches.length > 0 || detail.work_orders.length > 0 ? (
                  <div className="flex flex-wrap gap-2 p-4">
                    {detail.work_orders.map((w) => (
                      <span
                        key={w.id}
                        className="inline-flex items-center gap-2 rounded-full border border-[#e5e5e5] px-3 py-1 text-[12px]"
                      >
                        <Mono className="text-[11px]">{w.id}</Mono>
                        <span className="text-[#525252]">{w.fault_class}</span>
                        <Badge tone={w.status === "RESOLVED" ? "green" : "orange"}>
                          {w.status}
                        </Badge>
                      </span>
                    ))}
                    {detail.dispatches.map((d) => (
                      <span
                        key={d.id}
                        className="inline-flex items-center gap-2 rounded-full border border-[#e5e5e5] px-3 py-1 text-[12px]"
                      >
                        <span className="text-[#525252]">{d.responder_role}</span>
                        <span className="text-[#a3a3a3]">·</span>
                        <span className="text-[#525252]">{d.response_phase}</span>
                        <Badge tone="blue">{d.status}</Badge>
                      </span>
                    ))}
                  </div>
                ) : null}
                {detail.dispatches.length > 0 ? (
                  <div className="p-4">
                    <h3 className="text-[13px] font-semibold text-[#171717]">
                      Responder interface
                    </h3>
                    <p className="mt-1 max-w-[70ch] text-[13px] text-[#525252]">
                      The field screen for these dispatches lives at{" "}
                      <Mono className="text-[12px] font-medium text-[#171717]">
                        /respond/&lt;task_token&gt;
                      </Mono>
                      . Photo and voice capture happen there, and a capture that disagrees
                      with the record refuses the custody commit.
                    </p>
                    <p className="mt-1.5 max-w-[70ch] text-[13px] text-[#525252]">
                      The token is minted with the dispatch and handed back exactly once, as{" "}
                      <Mono className="text-[12px]">responder_path</Mono> in the{" "}
                      <Mono className="text-[12px]">dispatch_responder</Mono> result. This
                      read route strips it, so no page can rebuild the link.{" "}
                      <Mono className="text-[12px]">scripts/seed_demo.py</Mono> creates a
                      dispatch and prints the responder path it minted, which is how you
                      get one.
                    </p>
                  </div>
                ) : null}
              </div>
            )}
          </Card>

          <Card padded={false}>
            <CardHeader
              title="Deterministic receipts"
              subtitle="What actually happened, and what was refused"
              right={
                <span className="flex gap-1.5">
                  {refusals.length > 0 ? (
                    <Badge tone="red">{refusals.length} refused</Badge>
                  ) : null}
                  {duplicates.length > 0 ? (
                    <Badge tone="blue">{duplicates.length} replayed</Badge>
                  ) : null}
                </span>
              }
            />
            {detail.receipts.length === 0 ? (
              <Empty title="No receipts" body="No consequential action has been attempted." />
            ) : (
              <Table headers={["Action", "Actor", "Status", "Effect", "Detail"]} minWidth={760}>
                {detail.receipts.slice(-24).reverse().map((r) => (
                  <tr key={r.receipt_id} className={r.status === "REFUSED" ? "bg-[#fef2f2]" : ""}>
                    <Td className="whitespace-nowrap">
                      <span className="text-[13px] font-medium">
                        {r.action_type.replace(/_/g, " ").toLowerCase()}
                      </span>
                    </Td>
                    <Td>
                      <Mono className="text-[11px]">{r.actor_identity}</Mono>
                    </Td>
                    <Td>
                      <Badge
                        tone={
                          r.status === "COMMITTED"
                            ? "green"
                            : r.status === "REFUSED"
                              ? "red"
                              : "orange"
                        }
                        dot
                      >
                        {r.duplicate_returned ? "REPLAYED" : r.status}
                      </Badge>
                    </Td>
                    <Td>
                      <Mono className="text-[11px]">{r.effect_ref ?? "—"}</Mono>
                    </Td>
                    <Td className="max-w-[420px] text-[12px] text-[#525252]">
                      {r.refusal_reason ?? r.evidence_sources.join(", ") ?? ""}
                    </Td>
                  </tr>
                ))}
              </Table>
            )}
          </Card>

          <Card padded={false}>
            <CardHeader
              title="Custody reconciliation"
              subtitle={`${recon.committed.length} committed · ${recon.quarantined.length} quarantined · ${recon.in_flight.length} in flight · ${recon.unresolved.length} unresolved`}
              right={
                <Badge tone={recon.complete ? "green" : "orange"} dot>
                  {recon.complete ? "complete" : "incomplete"}
                </Badge>
              }
            />
            {detail.containers.length === 0 ? (
              <Empty title="No containers" body="No impact snapshot has been recorded." />
            ) : (
              <Table
                headers={["Container", "Study", "Priority", "Specimens", "Location", "Custody"]}
                minWidth={720}
              >
                {detail.containers.slice(0, 60).map((c) => (
                  <tr key={c.container_id}>
                    <Td>
                      <Mono className="font-medium text-[#171717]">{c.container_id}</Mono>
                    </Td>
                    <Td>
                      <Mono className="text-[11px]">{c.study_id}</Mono>
                    </Td>
                    <Td>
                      <Badge tone={c.priority_class === 1 ? "red" : c.priority_class === 2 ? "orange" : "neutral"}>
                        P{c.priority_class}
                      </Badge>
                    </Td>
                    <Td>
                      <Mono>{c.specimen_count}</Mono>
                    </Td>
                    <Td>
                      <Mono>{c.freezer_id}</Mono>
                    </Td>
                    <Td>
                      <Badge tone={custodyTone(c.custody_state)} dot>
                        {c.custody_state.replace(/_/g, " ")}
                      </Badge>
                    </Td>
                  </tr>
                ))}
              </Table>
            )}
            {detail.containers.length > 60 ? (
              <p className="border-t border-[#e5e5e5] px-4 py-2 text-[12px] text-[#737373]">
                Showing 60 of {detail.containers.length}. Every container is counted in the
                reconciliation above.
              </p>
            ) : null}
          </Card>
        </div>

        <div className="min-w-0 space-y-4">
          <Card padded={false}>
            <CardHeader
              title="Safety kernel"
              subtitle="Recomputed at this incident's evaluation instant"
              right={
                <Badge tone={failedInvariants.length === 0 ? "green" : "red"} dot>
                  {invariants.length - failedInvariants.length}/{invariants.length}
                </Badge>
              }
            />
            <Table headers={["", "", "Invariant", "Detail"]} minWidth={560}>
              {invariants.map((i) => (
                <InvariantRow key={i.invariant} result={i} />
              ))}
            </Table>
            <div className="border-t border-[#e5e5e5] px-4 py-3">
              <div className="flex flex-wrap items-baseline justify-between gap-2">
                <span className="text-[11px] tracking-wide text-[#737373] uppercase">
                  Evaluated as of
                </span>
                <Mono className="text-[12px] text-[#171717]">{detail.evaluated_as_of}</Mono>
              </div>
              <div className="mt-1 flex flex-wrap items-baseline justify-between gap-2">
                <span className="text-[11px] tracking-wide text-[#737373] uppercase">Basis</span>
                <Mono className="text-[11px]">{detail.evaluation_basis}</Mono>
              </div>
              <p className="mt-2 text-[12px] leading-relaxed text-[#737373]">
                {EVALUATION_BASIS[detail.evaluation_basis] ??
                  "The API reported an evaluation basis this page does not have a description for."}
              </p>
            </div>
          </Card>

          <Card padded={false}>
            <CardHeader
              title="Timeline"
              subtitle="Agent decisions and deterministic receipts, distinguished"
              right={<Mono>{timeline?.count ?? 0} events</Mono>}
            />
            <div className="max-h-[720px] overflow-y-auto">
              <Timeline events={(timeline?.events ?? []).slice().reverse()} />
            </div>
          </Card>

          <Card padded={false}>
            <CardHeader
              title="Cloud Trace"
              subtitle="Every tool call, effect, and specialist turn under one incident trace"
              right={
                <Badge tone={detail.trace.enabled ? "green" : "neutral"} dot={detail.trace.enabled}>
                  {detail.trace.enabled ? "exporting" : "not enabled"}
                </Badge>
              }
            />
            <div className="p-4">
              {detail.trace.root_trace_id ? (
                <>
                  <div className="text-[11px] tracking-wide text-[#737373] uppercase">
                    Root trace
                  </div>
                  <Mono className="mt-1 block break-all text-[12px] text-[#171717]">
                    {detail.trace.root_trace_id}
                  </Mono>
                  {detail.trace.console_url ? (
                    <div className="mt-3">
                      <a
                        href={detail.trace.console_url}
                        target="_blank"
                        rel="noreferrer noopener"
                        className="inline-block text-[13px] font-medium text-[#2563eb] hover:underline"
                      >
                        Open in Cloud Trace (needs project access) →
                      </a>
                      <p className="mt-1 text-[12px] leading-relaxed text-[#737373]">
                        That console only opens for someone holding IAM on the Google Cloud
                        project this deployment runs in. The recorded span counts below need
                        no access at all.
                      </p>
                    </div>
                  ) : null}
                  <p className="mt-3 text-[12px] leading-relaxed text-[#737373]">
                    {detail.trace.trace_ids.length} trace
                    {detail.trace.trace_ids.length === 1 ? "" : "s"} recorded on this
                    incident&apos;s receipts. Each receipt carries the trace it committed
                    under, so the ledger and the execution are joinable.
                  </p>
                </>
              ) : (
                <p className="text-[13px] leading-relaxed text-[#737373]">
                  No trace was recorded for this incident. Tracing is enabled with{" "}
                  <Mono>NIGHTSHIFT_TRACING=1</Mono> and exports to Cloud Trace when a
                  project is configured; it is deliberately inert otherwise, so a
                  tracing failure can never affect a rescue.
                </p>
              )}
            </div>

            <div className="border-t border-[#e5e5e5] px-4 py-3">
              <div className="flex flex-wrap items-baseline justify-between gap-2">
                <h3 className="text-[13px] font-semibold text-[#171717]">Recorded spans</h3>
                <Mono className="text-[11px]">
                  {RECORDED_TRACES.total_spans} spans · {RECORDED_TRACES.nightshift_traces} traces
                </Mono>
              </div>
              <p className="mt-1 text-[12px] leading-relaxed text-[#737373]">
                Read back from the Cloud Trace API over a {RECORDED_TRACES.window_hours} hour
                window on {RECORDED_TRACES.generated_at.slice(0, 10)} and committed to{" "}
                <Mono className="text-[11px]">evidence/traces.json</Mono>. It covers{" "}
                {RECORDED_TRACES.nightshift_traces} Night Shift traces out of{" "}
                {RECORDED_TRACES.traces_examined} examined, so these are campaign-wide
                counts rather than this incident&apos;s own spans. Every name below is one
                Night Shift creates itself, so their presence shows the instrumentation
                reached Cloud Trace rather than that something served HTTP.
              </p>
              <ul className="mt-2.5 space-y-1">
                {RECORDED_TRACES.top_spans.map((span) => (
                  <li key={span.name} className="flex items-baseline justify-between gap-3">
                    <Mono className="truncate text-[11px]">{span.name}</Mono>
                    <Mono className="shrink-0 text-[11px] font-medium text-[#171717]">
                      {span.count}
                    </Mono>
                  </li>
                ))}
              </ul>
              <p className="mt-2 text-[12px] text-[#737373]">
                {RECORDED_TRACES.top_spans.length} of {RECORDED_TRACES.distinct_span_names}{" "}
                distinct span names shown. The rest are in the committed file.
              </p>
            </div>
          </Card>

          <Card padded={false}>
            <CardHeader title="State transitions" subtitle="Every one guarded" />
            {incident.transitions.length === 0 ? (
              <Empty title="No transitions" body="The incident has not advanced yet." />
            ) : (
              <ol className="divide-y divide-[#e5e5e5]">
                {incident.transitions.map((t, index) => (
                  <li key={`${t.at}-${index}`} className="px-4 py-2.5">
                    <div className="flex items-center gap-2 text-[13px]">
                      <Mono className="text-[11px] text-[#a3a3a3]">{t.from_state}</Mono>
                      <span className="text-[#a3a3a3]">→</span>
                      <span className="font-medium text-[#171717]">{t.to_state}</span>
                    </div>
                    <p className="mt-0.5 text-[12px] text-[#737373]">{t.reason}</p>
                  </li>
                ))}
              </ol>
            )}
          </Card>
        </div>
      </div>
    </AppShell>
  );
}
