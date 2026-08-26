import { AppShell, ApiDown, PageHeader } from "@/components/shell";
import { Badge, Card, CardHeader, Mono, Table, Td } from "@/components/ui";
import { getOverview } from "@/lib/api";

export const dynamic = "force-dynamic";

export default async function FreezersPage() {
  const overview = await getOverview();

  return (
    <AppShell active="/app/freezers">
      <PageHeader
        title="Freezer estate"
        subtitle="Authoritative telemetry. Reading age matters as much as temperature — a destination commit is refused on a stale reading even if the number looks fine."
      />
      {!overview ? (
        <ApiDown what="The freezer estate" />
      ) : (
        <div className="space-y-4">
          <Card padded={false}>
            <CardHeader title="All units" subtitle={`Evaluated ${overview.evaluated_at}`} />
            <Table
              headers={["Freezer", "Label", "Zone", "State", "Temp", "Setpoint", "Alarm", "Occupied", "Free", "Backup", "Hold", "Reading age"]}
              minWidth={1100}
            >
              {overview.freezers.map((f) => (
                <tr key={f.freezer_id} className={f.above_alarm ? "bg-[#fef2f2]" : ""}>
                  <Td>
                    <Mono className="font-medium text-[#171717]">{f.freezer_id}</Mono>
                  </Td>
                  <Td className="text-[13px] whitespace-nowrap">{f.label}</Td>
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
                    <span className={`mono text-[13px] font-medium ${f.above_alarm ? "text-[#dc2626]" : "text-[#171717]"}`}>
                      {f.current_temp_c.toFixed(1)}°C
                    </span>
                  </Td>
                  <Td><Mono>{f.setpoint_c.toFixed(0)}°C</Mono></Td>
                  <Td><Mono>{f.alarm_high_c.toFixed(0)}°C</Mono></Td>
                  <Td><Mono>{f.occupied_slots}</Mono></Td>
                  <Td><Mono className="font-medium text-[#171717]">{f.free_slots}</Mono></Td>
                  <Td>{f.is_backup_qualified ? <Badge tone="blue">backup</Badge> : <span className="text-[#a3a3a3]">—</span>}</Td>
                  <Td>{f.hold_active ? <Badge tone="orange" dot>held</Badge> : <span className="text-[#a3a3a3]">—</span>}</Td>
                  <Td>
                    <span className={`mono text-[12px] ${f.reading_age_s > 900 ? "text-[#dc2626]" : "text-[#737373]"}`}>
                      {Math.round(f.reading_age_s)}s
                    </span>
                  </Td>
                </tr>
              ))}
            </Table>
          </Card>
          <Card>
            <h2 className="text-[14px] font-semibold text-[#171717]">Why a freezer with free slots may still be unusable</h2>
            <p className="mt-1.5 max-w-[78ch] text-[13px] leading-relaxed text-[#525252]">
              A destination has to be backup-qualified, currently below the ultra-low
              ceiling, freshly read, and free of a containment hold. In this estate F-24
              has the most free slots and is rejected on every reservation attempt because
              it sits above the ceiling. Free space is not availability.
            </p>
          </Card>
        </div>
      )}
    </AppShell>
  );
}
