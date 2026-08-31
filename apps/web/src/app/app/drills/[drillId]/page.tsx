import Link from "next/link";
import { notFound } from "next/navigation";

import { AppShell, PageHeader } from "@/components/shell";
import { Badge, Card, CardHeader, Mono, Table, Td } from "@/components/ui";
import { getDrill } from "@/lib/api";

export const revalidate = 30;

/**
 * Zero denials is a finding. A run recorded before the counter existed is not, and
 * printing 0 for it would invent a measurement the campaign never took.
 */
function counted(value: unknown): string {
  return typeof value === "number" ? value.toLocaleString() : "—";
}

export default async function DrillDetail({ params }: { params: Promise<{ drillId: string }> }) {
  const { drillId } = await params;
  const result = await getDrill(drillId);
  if (result.missing) notFound();
  // A failed API is not an unknown drill, and error.tsx says which one happened.
  if (!result.data) {
    throw result.failure ?? new Error(`Drill ${drillId} could not be loaded.`);
  }
  const data = result.data;
  const { drill, runs } = data;

  return (
    <AppShell active="/app/drills">
      <PageHeader
        title={`${drill.id} — ${drill.title}`}
        subtitle={drill.description}
        right={
          <>
            <Badge tone="neutral">{drill.family}</Badge>
            <Link href="/app/drills" className="rounded-[8px] border border-[#e5e5e5] px-3 py-1.5 text-[13px] font-medium hover:bg-[#f5f5f5]">
              All drills
            </Link>
          </>
        }
      />

      <div className="grid gap-4 lg:grid-cols-2">
        <Card padded={false}>
          <CardHeader title="Expectations" subtitle="Properties of the outcome, not scenario identifiers" />
          <ul className="divide-y divide-[#e5e5e5]">
            {drill.expectations.map((e) => (
              <li key={e.key} className="px-4 py-2.5">
                <Mono className="text-[11px] text-[#2563eb]">{e.key}</Mono>
                <p className="mt-0.5 text-[13px] text-[#404040]">{e.description}</p>
              </li>
            ))}
          </ul>
        </Card>

        <Card padded={false}>
          <CardHeader title="Injected faults" subtitle="Keyed on (tool, action id, call number) so a rerun reproduces exactly" />
          {drill.faults.length === 0 ? (
            <div className="px-4 py-8 text-center text-[13px] text-[#737373]">
              No faults injected. This drill tests behaviour under normal conditions.
            </div>
          ) : (
            <Table headers={["Tool", "Call", "Kind"]} minWidth={420}>
              {drill.faults.map((f, i) => (
                <tr key={`${f.tool}-${i}`}>
                  <Td><Mono className="text-[12px]">{f.tool}</Mono></Td>
                  <Td><Mono>{f.call_number === 0 ? "every" : f.call_number}</Mono></Td>
                  <Td>
                    <Badge tone="orange">
                      {f.kind === "commit_loss" ? "commits, response lost" : "never runs"}
                    </Badge>
                  </Td>
                </tr>
              ))}
            </Table>
          )}
        </Card>
      </div>

      <Card padded={false} className="mt-4">
        <CardHeader title="Runs" subtitle={`${data.run_count} recorded run(s) across the campaign`} />
        {runs.length === 0 ? (
          <div className="px-4 py-10 text-center text-[13px] text-[#737373]">
            No campaign runs recorded for this drill yet.
          </div>
        ) : (
          <Table
            headers={[
              "#",
              "Driver",
              "Seed",
              "Result",
              "Final state",
              "Faults",
              "Tool calls",
              "Denied",
              "Model calls",
              "Reconciled",
              "Unmet",
              "Time",
            ]}
            minWidth={1160}
          >
            {runs.map((r) => {
              const row = r as Record<string, unknown>;
              const passed = Boolean(row.passed);
              const infra = Boolean(row.infrastructure_error);
              const unmet = (row.unmet_expectations as string[]) ?? [];
              const denials = row.tool_denials;
              return (
                <tr key={String(row.run_index)} className={!passed && !infra ? "bg-[#fef2f2]" : ""}>
                  <Td><Mono>{String(row.run_index)}</Mono></Td>
                  <Td className="text-[13px]">{String(row.driver)}</Td>
                  <Td><Mono className="text-[11px]">{String(row.seed)}</Mono></Td>
                  <Td>
                    <Badge tone={infra ? "orange" : passed ? "green" : "red"} dot>
                      {infra ? "INFRA" : passed ? "PASS" : "FAIL"}
                    </Badge>
                  </Td>
                  <Td><Mono className="text-[11px]">{String(row.final_state)}</Mono></Td>
                  <Td><Mono>{String(row.faults_injected)}</Mono></Td>
                  <Td><Mono>{counted(row.tool_calls)}</Mono></Td>
                  <Td>
                    <Mono
                      className={typeof denials === "number" && denials > 0 ? "text-[#991b1b]" : ""}
                    >
                      {counted(denials)}
                    </Mono>
                  </Td>
                  <Td><Mono>{counted(row.model_calls)}</Mono></Td>
                  <Td><Mono>{String(row.committed)}/{String(row.total_containers)}</Mono></Td>
                  <Td className="text-[12px] text-[#991b1b]">{unmet.join(", ") || "—"}</Td>
                  <Td><Mono className="text-[11px]">{String(row.wall_clock_s)}s</Mono></Td>
                </tr>
              );
            })}
          </Table>
        )}
      </Card>
    </AppShell>
  );
}
