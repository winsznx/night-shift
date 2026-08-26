import { AppShell, ApiDown, PageHeader } from "@/components/shell";
import { Badge, Card, CardHeader, Metric, Mono, Table, Td } from "@/components/ui";
import { getOverview } from "@/lib/api";

export const dynamic = "force-dynamic";

export default async function CapacityPage() {
  const overview = await getOverview();
  const backups = overview?.freezers.filter((f) => f.is_backup_qualified) ?? [];
  const ceiling = -60;

  return (
    <AppShell active="/app/capacity">
      <PageHeader
        title="Capacity"
        subtitle="Reservations are committed inside a database transaction, so two incidents racing for the last slots cannot both win."
      />
      {!overview ? (
        <ApiDown what="Capacity" />
      ) : (
        <div className="space-y-4">
          <Card padded={false}>
            <div className="grid grid-cols-2 gap-5 p-4 sm:grid-cols-4">
              <Metric label="Estate slots" value={overview.capacity.total_slots} />
              <Metric label="Occupied" value={overview.capacity.occupied_slots} />
              <Metric label="Reserved" value={overview.capacity.reserved_slots} hint="withheld from other incidents" />
              <Metric label="Backup free" value={overview.capacity.backup_free_slots} hint="before eligibility checks" />
            </div>
          </Card>

          <Card padded={false}>
            <CardHeader
              title="Backup destinations"
              subtitle="Eligibility is decided against current state, not a flag on the record"
            />
            <Table headers={["Freezer", "Temp", "Free slots", "Reading age", "Eligible", "Reason"]} minWidth={780}>
              {backups.map((f) => {
                const tooWarm = f.current_temp_c > ceiling;
                const stale = f.reading_age_s > 900;
                const held = f.hold_active;
                const noRoom = f.free_slots <= 0;
                const reasons = [
                  tooWarm ? `above the ${ceiling}°C ceiling` : null,
                  stale ? "reading is stale" : null,
                  held ? "under containment hold" : null,
                  noRoom ? "no free slots" : null,
                ].filter(Boolean);
                return (
                  <tr key={f.freezer_id}>
                    <Td><Mono className="font-medium text-[#171717]">{f.freezer_id}</Mono></Td>
                    <Td>
                      <span className={`mono text-[13px] ${tooWarm ? "text-[#dc2626]" : "text-[#171717]"}`}>
                        {f.current_temp_c.toFixed(1)}°C
                      </span>
                    </Td>
                    <Td><Mono>{f.free_slots}</Mono></Td>
                    <Td><Mono className="text-[12px] text-[#737373]">{Math.round(f.reading_age_s)}s</Mono></Td>
                    <Td>
                      <Badge tone={reasons.length === 0 ? "green" : "red"} dot>
                        {reasons.length === 0 ? "eligible" : "ineligible"}
                      </Badge>
                    </Td>
                    <Td className="text-[13px] text-[#525252]">{reasons.join("; ") || "—"}</Td>
                  </tr>
                );
              })}
            </Table>
          </Card>
        </div>
      )}
    </AppShell>
  );
}
