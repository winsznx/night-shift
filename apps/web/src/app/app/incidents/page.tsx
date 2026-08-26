import Link from "next/link";

import { AppShell, ApiDown, PageHeader } from "@/components/shell";
import { Badge, Card, Empty, Mono, StateBadge, Table, Td, timeAgo } from "@/components/ui";
import { getOverview } from "@/lib/api";

export const revalidate = 3;

export default async function IncidentsPage() {
  const overview = await getOverview();

  return (
    <AppShell active="/app/incidents">
      <PageHeader
        title="Incidents"
        subtitle="Every incident in this namespace. A partial rescue is never presented as a success."
      />
      {!overview ? (
        <ApiDown what="The incident list" />
      ) : (
        <Card padded={false}>
          {overview.incidents.length === 0 ? (
            <Empty
              title="No incidents"
              body="Nothing has crossed an alarm threshold in this namespace yet."
            />
          ) : (
            <Table
              headers={["Incident", "State", "Severity", "Freezer", "Impacted", "Committed", "Unresolved", "Opened", "Closed"]}
              minWidth={960}
            >
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
                    <Badge tone={i.severity === "SEV1" ? "red" : "orange"}>{i.severity}</Badge>
                  </Td>
                  <Td>
                    <Mono>{i.failed_freezer_id}</Mono>
                  </Td>
                  <Td>
                    <Mono>{i.impacted_containers}</Mono>
                  </Td>
                  <Td>
                    <Mono>{i.committed}</Mono>
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
                  <Td className="text-[13px] text-[#737373]">
                    {timeAgo(i.opened_at, overview.evaluated_at)}
                  </Td>
                  <Td className="text-[13px] text-[#737373]">
                    {i.closed_at ? timeAgo(i.closed_at, overview.evaluated_at) : "—"}
                  </Td>
                </tr>
              ))}
            </Table>
          )}
        </Card>
      )}
    </AppShell>
  );
}
