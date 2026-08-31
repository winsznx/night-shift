import Link from "next/link";

import { AppShell, ApiDown, PageHeader } from "@/components/shell";
import {
  Badge,
  Card,
  CardHeader,
  Empty,
  Metric,
  Mono,
  StateBadge,
  Table,
  Td,
} from "@/components/ui";
import { getDrills, getOverview } from "@/lib/api";

export const dynamic = "force-dynamic";

export default async function OperationsOverview() {
  const [overview, drills] = await Promise.all([getOverview(), getDrills()]);

  return (
    <AppShell active="/app">
      <PageHeader
        title="Operations"
        subtitle="Estate state, active incidents, and fleet qualification health."
      />

      {!overview ? (
        <ApiDown what="The operations overview" />
      ) : (
        <div className="space-y-5">
          <Card padded={false}>
            <div className="grid grid-cols-2 gap-5 p-4 sm:grid-cols-3 lg:grid-cols-5">
              <Metric
                label="Active incidents"
                value={overview.active_incidents}
                hint={`${overview.total_incidents} total`}
                tone={overview.active_incidents > 0 ? "warn" : "default"}
              />
              <Metric
                label="Freezers above alarm"
                value={overview.freezers.filter((f) => f.above_alarm).length}
                hint={`of ${overview.freezers.length}`}
                tone={overview.freezers.some((f) => f.above_alarm) ? "bad" : "good"}
              />
              <Metric
                label="Containment holds"
                value={overview.freezers.filter((f) => f.hold_active).length}
                hint="normal ops frozen"
              />
              <Metric
                label="Backup free slots"
                value={overview.capacity.backup_free_slots}
                hint={`${overview.capacity.reserved_slots} reserved`}
              />
              <Metric
                label="Unresolved containers"
                value={overview.incidents.reduce((n, i) => n + i.unresolved, 0)}
                hint="blocks closure"
                tone={
                  overview.incidents.some((i) => i.unresolved > 0) ? "bad" : "good"
                }
              />
            </div>
          </Card>

          <div className="grid items-start gap-5 lg:grid-cols-[1.4fr_1fr]">
            <Card padded={false}>
              <CardHeader
                title="Incidents"
                subtitle="Newest first"
                right={
                  <Link
                    href="/app/incidents"
                    className="text-[13px] font-medium text-[#2563eb] hover:underline"
                  >
                    All incidents
                  </Link>
                }
              />
              {overview.incidents.length === 0 ? (
                <Empty
                  title="No incidents"
                  body="Nothing has crossed an alarm threshold in this namespace yet."
                />
              ) : (
                <Table headers={["Incident", "State", "Freezer", "Impacted", "Unresolved"]} minWidth={520}>
                  {overview.incidents.map((i) => (
                    <tr key={i.incident_id} className="hover:bg-[#f5f5f5]">
                      <Td>
                        <Link
                          href={`/app/incidents/${i.incident_id}`}
                          className="mono text-[13px] font-medium text-[#2563eb] hover:underline"
                        >
                          {i.incident_id}
                        </Link>
                      </Td>
                      <Td>
                        <StateBadge state={i.state} />
                      </Td>
                      <Td>
                        <Mono>{i.failed_freezer_id}</Mono>
                      </Td>
                      <Td>
                        <span className="mono text-[13px]">
                          {i.committed}/{i.impacted_containers}
                        </span>
                      </Td>
                      <Td>
                        {i.unresolved > 0 ? (
                          <Badge tone="red" dot>
                            {i.unresolved}
                          </Badge>
                        ) : (
                          <Badge tone="green">0</Badge>
                        )}
                      </Td>
                    </tr>
                  ))}
                </Table>
              )}
            </Card>

            <Card padded={false}>
              <CardHeader
                title="Fleet qualification"
                subtitle="From the published drill corpus"
                right={
                  <Link
                    href="/app/drills"
                    className="text-[13px] font-medium text-[#2563eb] hover:underline"
                  >
                    Drills
                  </Link>
                }
              />
              <div className="p-4">
                {drills?.campaign?.by_driver ? (
                  <div className="space-y-3">
                    {Object.entries(drills.campaign.by_driver).map(([driver, block]) => (
                      <div key={driver} className="rounded-[8px] border border-[#e5e5e5] p-3">
                        <div className="flex items-center justify-between">
                          <span className="text-[13px] font-medium text-[#171717]">
                            {driver === "scripted" ? "Deterministic tier" : "Live agent tier"}
                          </span>
                          <Badge tone={block.passed === block.scored_runs ? "green" : "orange"}>
                            {block.passed}/{block.scored_runs} passed
                          </Badge>
                        </div>
                        <dl className="mt-2.5 grid grid-cols-2 gap-x-3 gap-y-1 text-[12px]">
                          <dt className="text-[#737373]">Overbooking violations</dt>
                          <dd className="mono text-right text-[#171717]">
                            {block.capacity_overbooking_violations}
                          </dd>
                          <dt className="text-[#737373]">Duplicate effects</dt>
                          <dd className="mono text-right text-[#171717]">
                            {block.duplicate_effect_violations}
                          </dd>
                          <dt className="text-[#737373]">Faults injected</dt>
                          <dd className="mono text-right text-[#171717]">
                            {block.faults_injected_total}
                          </dd>
                          <dt className="text-[#737373]">Denials recorded</dt>
                          <dd className="mono text-right text-[#171717]">
                            {block.authorization_denials_total}
                          </dd>
                        </dl>
                      </div>
                    ))}
                  </div>
                ) : (
                  <Empty
                    title="No campaign yet"
                    body="Run `make evidence` to generate measured drill results."
                  />
                )}
              </div>
            </Card>
          </div>

          <Card padded={false}>
            <CardHeader
              title="Freezer estate"
              subtitle="Authoritative telemetry"
              right={
                <Link
                  href="/app/freezers"
                  className="text-[13px] font-medium text-[#2563eb] hover:underline"
                >
                  Details
                </Link>
              }
            />
            <Table
              headers={["Freezer", "Zone", "State", "Temp", "Setpoint", "Free", "Backup", "Hold", "Reading"]}
              minWidth={860}
            >
              {overview.freezers.map((f) => (
                <tr key={f.freezer_id} className="hover:bg-[#f5f5f5]">
                  <Td>
                    <Mono className="font-medium text-[#171717]">{f.freezer_id}</Mono>
                  </Td>
                  <Td className="text-[13px] text-[#737373]">{f.zone}</Td>
                  <Td>
                    <Badge
                      tone={
                        f.state === "FAILED"
                          ? "red"
                          : f.state === "SUSPECT" || f.state === "RECOVERING"
                            ? "orange"
                            : "green"
                      }
                      dot
                    >
                      {f.state}
                    </Badge>
                  </Td>
                  <Td>
                    <span
                      className={`mono text-[13px] font-medium ${f.above_alarm ? "text-[#dc2626]" : "text-[#171717]"}`}
                    >
                      {f.current_temp_c.toFixed(1)}°C
                    </span>
                  </Td>
                  <Td>
                    <Mono>{f.setpoint_c.toFixed(0)}°C</Mono>
                  </Td>
                  <Td>
                    <Mono>
                      {f.free_slots}/{f.total_slots}
                    </Mono>
                  </Td>
                  <Td>{f.is_backup_qualified ? <Badge tone="blue">backup</Badge> : null}</Td>
                  <Td>{f.hold_active ? <Badge tone="orange" dot>held</Badge> : null}</Td>
                  <Td className="text-[13px] text-[#737373]">{Math.round(f.reading_age_s)}s ago</Td>
                </tr>
              ))}
            </Table>
          </Card>
        </div>
      )}
    </AppShell>
  );
}
