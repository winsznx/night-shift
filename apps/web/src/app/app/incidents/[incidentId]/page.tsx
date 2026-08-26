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

export const revalidate = 3;

export default async function IncidentDetail({
  params,
}: {
  params: Promise<{ incidentId: string }>;
}) {
  const { incidentId } = await params;
  const [detail, timeline] = await Promise.all([
    getIncident(incidentId),
    getTimeline(incidentId),
  ]);
  if (!detail) notFound();

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
                <Mono className="text-[#991b1b]">{i.invariant}</Mono> {i.title} — {i.detail}
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
              subtitle="Recomputed from current state"
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
