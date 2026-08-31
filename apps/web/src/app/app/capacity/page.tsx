import { AppShell, ApiDown, PageHeader } from "@/components/shell";
import { Badge, Card, CardHeader, Metric, Mono, Table, Td } from "@/components/ui";
import { getOverview } from "@/lib/api";

export const dynamic = "force-dynamic";

/** N4 refuses a destination whose newest reading is older than this. Mirrors
 * `KernelConfig.destination_temp_max_age_s` in `nightshift/safety_kernel/config.py`;
 * the API publishes no kernel thresholds, so the page restates the number rather than
 * implying a rule of its own. */
const FRESHNESS_WINDOW_S = 900;

export default async function CapacityPage() {
  const overview = await getOverview();
  const backups = overview?.freezers.filter((f) => f.is_backup_qualified) ?? [];
  const ceiling = -60;
  const staleCount = backups.filter((f) => f.reading_age_s > FRESHNESS_WINDOW_S).length;

  return (
    <AppShell active="/app/capacity">
      <PageHeader
        title="Capacity"
        subtitle="Reservations are committed inside a database transaction, so two incidents racing for the last slots cannot both win."
      />
      {!overview ? (
        <ApiDown what="Capacity" />
      ) : (
        <div className="space-y-5">
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
                const stale = f.reading_age_s > FRESHNESS_WINDOW_S;
                const held = f.hold_active;
                const noRoom = f.free_slots <= 0;
                const reasons = [
                  tooWarm ? `above the ${ceiling}°C ceiling` : null,
                  stale
                    ? `last read ${Math.round(f.reading_age_s)}s ago, past the ${FRESHNESS_WINDOW_S}s N4 freshness window`
                    : null,
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
            <div className="border-t border-[#e5e5e5] px-4 py-3">
              <p className="max-w-[80ch] text-[13px] leading-relaxed text-[#525252]">
                A stale destination is refused by design. N4 will not accept temperature
                evidence older than {FRESHNESS_WINDOW_S} seconds, because a reading that
                old cannot show a freezer is cold right now. Telemetry in this estate is
                seeded in batches, so between refreshes every reading ages out together
                and the whole backup set turns ineligible at once.
                {staleCount > 0
                  ? ` ${staleCount} of ${backups.length} destinations sit past the window right now, and a commit against any of them is refused. That is the freshness check holding.`
                  : ""}
              </p>
            </div>
          </Card>
        </div>
      )}
    </AppShell>
  );
}
