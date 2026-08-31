import { AppShell, ApiDown, PageHeader } from "@/components/shell";
import { Badge, Card, CardHeader, Mono, Table, Td } from "@/components/ui";
import { type FleetAgent, getFleet } from "@/lib/api";

export const dynamic = "force-dynamic";

const DOMAIN_COLUMNS = ["telemetry", "inventory", "capacity", "facilities", "custody"];

/** `/api/fleet` reports where each identity came from, but the shared `FleetAgent` type
 * has not picked the field up yet. Widening it here keeps the page honest without
 * loosening the type for every other caller. */
function identitySource(
  agent: FleetAgent & { identity_source?: string | null },
): string | null {
  return agent.identity_source ?? null;
}

/** Identity is shown exactly as reported and never reconstructed from the agent name.
 * A guessed principal renders identically to a real one, which is the confusion this
 * page exists to prevent. */
function IdentityCell({ agent }: { agent: FleetAgent }) {
  if (!agent.identity) {
    return (
      <span className="flex flex-col gap-0.5">
        <span className="mono text-[11px] text-[#a3a3a3]">no identity reported</span>
        <span className="text-[11px] leading-snug text-[#737373]">
          The fleet API returned none for this agent.
        </span>
      </span>
    );
  }
  const source = identitySource(agent);
  const caption =
    source === "provisioned-service-account"
      ? "Provisioned Google service account. The gateway mints this agent's outbound OIDC token as it."
      : source === "agent-registry-snapshot"
        ? "Recorded in infra/registry-snapshot.json when the fleet was deployed."
        : null;
  return (
    <span className="flex flex-col gap-0.5">
      <Mono className="text-[11px]">{agent.identity}</Mono>
      {caption ? (
        <span className="max-w-[38ch] text-[11px] leading-snug text-[#737373]">
          {caption}
        </span>
      ) : null}
    </span>
  );
}

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
        <div className="space-y-5">
          <Card padded={false}>
            <CardHeader
              title="Qualification and identity"
              subtitle="A revision with no qualification record is treated as unqualified, never as probably fine"
            />
            <Table
              headers={[
                "Agent",
                "Revision",
                "Qualification",
                "Traffic",
                "Runtime",
                "Identity",
                "Latest drill",
                "Tools",
              ]}
              minWidth={1120}
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
                    {a.runtime_resource ? (
                      <Mono className="text-[11px]">{a.runtime_resource}</Mono>
                    ) : (
                      <span className="text-[12px] text-[#737373]">
                        Cloud Run (not managed Agent Runtime)
                      </span>
                    )}
                  </Td>
                  <Td>
                    <IdentityCell agent={a} />
                  </Td>
                  <Td>
                    {a.latest_drill ? (
                      <span
                        className="flex items-center gap-2"
                        title={a.latest_drill.scope}
                      >
                        <Badge tone={a.latest_drill.outcome === "PASS" ? "green" : "red"} dot>
                          {a.latest_drill.outcome}
                        </Badge>
                        <Mono className="text-[11px] text-[#737373]">
                          {a.latest_drill.corpus_version ?? ""}
                        </Mono>
                      </span>
                    ) : (
                      <span className="text-[12px] text-[#737373]">
                        No qualification run on record
                      </span>
                    )}
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

          <Card>
            <h2 className="text-[14px] font-semibold text-[#171717]">
              What &ldquo;identity&rdquo; means here
            </h2>
            {/* 24 is the scripted tier's authorization_denials_total in
                evidence/campaign/metrics.json, restated in LIMITATIONS.md. The fleet
                endpoint carries no campaign counts, so the figure is stated as a literal
                here rather than derived from data this page has. */}
            <p className="mt-1.5 max-w-[80ch] text-[13px] leading-relaxed text-[#525252]">
              Each agent has its own provisioned Google service account, and the gateway
              mints that agent&rsquo;s outbound OIDC token as it. The permission matrix
              below is enforced twice in our own code: the tool broker checks it on every
              call, and each domain service checks it again before it acts. All 24
              authorization denials recorded in the drill corpus are ours, because the
              corpus runs in-process where there is no network hop for Cloud Run to
              refuse.
            </p>
            <p className="mt-2 max-w-[80ch] text-[13px] leading-relaxed text-[#525252]">
              One denial is Google&rsquo;s. <Mono>evidence/iam-denial.json</Mono> records{" "}
              <Mono>ns-dispatch</Mono> taking an HTTP 403 from the Cloud Run edge on the
              Inventory service while <Mono>ns-impact</Mono> gets 200 on the same route. A
              broken endpoint would have refused both. That single platform denial is
              reported on its own and is never pooled into the corpus counts.
            </p>
            <p className="mt-2 max-w-[80ch] text-[13px] leading-relaxed text-[#525252]">
              Agents are not registered as managed Agent Registry or Agent Runtime
              resources on this deployment. That is recorded on the specific claims it
              affects rather than glossed over. See <Mono>LIMITATIONS.md</Mono>.
            </p>
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
