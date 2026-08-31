import { AppShell, ApiDown, PageHeader } from "@/components/shell";
import { Badge, Card, CardHeader, Mono, Table, Td } from "@/components/ui";
import { getOverview } from "@/lib/api";

export const dynamic = "force-dynamic";

/** Mirrors `KernelConfig.destination_temp_ceiling_c` and
 * `destination_temp_max_age_s` in `nightshift/safety_kernel/config.py`. The API
 * publishes no kernel thresholds, so the page restates them rather than implying a
 * rule of its own. */
const CEILING_C = -60;
const FRESHNESS_WINDOW_S = 900;

export default async function FreezersPage() {
  const overview = await getOverview();

  /* The roomiest unit is read off the live rows. A named winner written into the copy
     goes wrong the moment the estate changes, and this page is the one that argues free
     space and availability are different things. */
  const roomiest = overview?.freezers.length
    ? overview.freezers.reduce((best, f) => (f.free_slots > best.free_slots ? f : best))
    : null;
  const roomiestBlockers = roomiest
    ? [
        roomiest.is_backup_qualified ? null : "is not backup-qualified",
        roomiest.current_temp_c > CEILING_C ? `sits above the ${CEILING_C}°C ceiling` : null,
        roomiest.reading_age_s > FRESHNESS_WINDOW_S
          ? `was last read ${Math.round(roomiest.reading_age_s)}s ago, past the ${FRESHNESS_WINDOW_S}s freshness window`
          : null,
        roomiest.hold_active ? "is under a containment hold" : null,
      ].filter((reason): reason is string => reason !== null)
    : [];
  const roomiestRefusal =
    roomiestBlockers.length > 1
      ? `${roomiestBlockers.slice(0, -1).join(", ")} and ${roomiestBlockers[roomiestBlockers.length - 1]}`
      : roomiestBlockers[0];

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
                    <span className={`mono text-[12px] ${f.reading_age_s > FRESHNESS_WINDOW_S ? "text-[#dc2626]" : "text-[#737373]"}`}>
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
              ceiling, freshly read, and free of a containment hold.{" "}
              {roomiest ? (
                <>
                  Right now {roomiest.freezer_id} has the most free slots at{" "}
                  {roomiest.free_slots}.{" "}
                  {roomiestRefusal
                    ? `A reservation against it is still refused because it ${roomiestRefusal}.`
                    : "It clears all four gates, so it can take a reservation."}{" "}
                </>
              ) : null}
              Free space is not availability.
            </p>
          </Card>
        </div>
      )}
    </AppShell>
  );
}
