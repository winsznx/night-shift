import { AppShell, ApiDown, PageHeader } from "@/components/shell";
import { Badge, Card, CardHeader, Mono, Table, Td } from "@/components/ui";
import { getFleet } from "@/lib/api";

export const revalidate = 30;

const DOMAIN_COLUMNS = ["telemetry", "inventory", "capacity", "facilities", "custody"];

export default async function FleetPage() {
  const fleet = await getFleet();

  return (
    <AppShell active="/app/fleet">
      <PageHeader
        title="Agent fleet"
        subtitle="Six specialists, six authority boundaries. An agent cannot see a tool it has no authority for, the broker refuses the call, and the service refuses it again."
      />

      {!fleet ? (
        <ApiDown what="The fleet view" />
      ) : (
        <div className="space-y-4">
          <Card padded={false}>
            <CardHeader
              title="Qualification and identity"
              subtitle="A revision with no qualification record is treated as unqualified, never as probably fine"
            />
            <Table
              headers={["Agent", "Revision", "Qualification", "Traffic", "Identity", "Tools"]}
              minWidth={860}
            >
              {fleet.agents.map((a) => (
                <tr key={a.agent}>
                  <Td>
                    <span className="text-[13px] font-medium text-[#171717]">{a.agent}</span>
                  </Td>
                  <Td>
                    <Mono>{a.revision}</Mono>
                  </Td>
                  <Td>
                    <Badge
                      tone={
                        a.qualification === "ACTIVE" || a.qualification === "QUALIFIED"
                          ? "green"
                          : a.qualification === "BLOCKED"
                            ? "red"
                            : "orange"
                      }
                      dot
                    >
                      {a.qualification}
                    </Badge>
                  </Td>
                  <Td>
                    <Mono>{a.traffic_percent}%</Mono>
                  </Td>
                  <Td>
                    <Mono className="text-[11px]">{a.identity ?? "local principal"}</Mono>
                  </Td>
                  <Td>
                    <span className="flex items-center gap-2">
                      <Badge tone="blue">{a.allowed_tools.length} allowed</Badge>
                      <Badge tone="neutral">{a.forbidden_tools.length} denied</Badge>
                    </span>
                  </Td>
                </tr>
              ))}
            </Table>
          </Card>

          <Card padded={false}>
            <CardHeader
              title="Permission matrix"
              subtitle="Read the gaps: the Dispatch Agent has no inventory column at all, which is what makes the poisoned-vendor drill a real denial rather than a prompt"
            />
            <Table headers={["Agent", ...DOMAIN_COLUMNS]} minWidth={900}>
              {Object.entries(fleet.permission_matrix).map(([agent, row]) => (
                <tr key={agent}>
                  <Td className="whitespace-nowrap">
                    <span className="text-[13px] font-medium text-[#171717]">{agent}</span>
                  </Td>
                  {DOMAIN_COLUMNS.map((col) => {
                    const value = row[col] ?? "no";
                    const denied = value === "no";
                    const writes = value.includes("write");
                    return (
                      <Td key={col}>
                        {denied ? (
                          <span className="mono text-[12px] text-[#a3a3a3]">—</span>
                        ) : (
                          <Badge tone={writes ? "orange" : "blue"}>{value}</Badge>
                        )}
                      </Td>
                    );
                  })}
                </tr>
              ))}
            </Table>
          </Card>

          <div className="grid gap-4 lg:grid-cols-2">
            <Card padded={false}>
              <CardHeader
                title="Operational skills"
                subtitle="Content-addressed procedural playbooks. The hash is the revision, so editing one changes its reference rather than rewriting history."
              />
              <Table headers={["Skill", "Revision", "Governance"]} minWidth={520}>
                {fleet.skills.map((s) => (
                  <tr key={s.name}>
                    <Td>
                      <span className="text-[13px] font-medium">{s.name}</span>
                    </Td>
                    <Td>
                      <Mono className="text-[11px]">{s.revision}</Mono>
                    </Td>
                    <Td>
                      {s.managed_resource ? (
                        <Badge tone="green">Agent Registry</Badge>
                      ) : (
                        <Badge tone="neutral">content-addressed</Badge>
                      )}
                    </Td>
                  </tr>
                ))}
              </Table>
            </Card>

            <Card padded={false}>
              <CardHeader
                title="Tool registry"
                subtitle="Unregistered tools are unreachable by default"
              />
              <div className="max-h-[420px] overflow-y-auto">
                <Table headers={["Tool", "Service", "Domain", ""]} minWidth={560}>
                  {fleet.tool_registry.map((t) => (
                    <tr key={t.name}>
                      <Td>
                        <Mono className="text-[12px] text-[#171717]">{t.name}</Mono>
                      </Td>
                      <Td className="text-[13px] text-[#525252]">{t.service}</Td>
                      <Td>
                        <Mono className="text-[11px]">{t.domain}</Mono>
                      </Td>
                      <Td>{t.mutating ? <Badge tone="orange">mutating</Badge> : null}</Td>
                    </tr>
                  ))}
                </Table>
              </div>
            </Card>
          </div>
        </div>
      )}
    </AppShell>
  );
}
