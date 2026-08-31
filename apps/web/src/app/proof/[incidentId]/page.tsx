import Link from "next/link";
import { notFound } from "next/navigation";

import { Logo } from "@/components/shell";
import { Badge, Card, CardHeader, Mono, Table, Td } from "@/components/ui";
import { getProof } from "@/lib/api";

export const revalidate = 30;

const STATUS_TONE = { PASS: "green", MISMATCH: "red", PARTIAL: "orange" } as const;

export default async function ProofPage({
  params,
}: {
  params: Promise<{ incidentId: string }>;
}) {
  const { incidentId } = await params;
  const proof = await getProof(incidentId);
  if (!proof) notFound();

  const v = proof.verification;
  const manifest = proof.manifest as Record<string, unknown>;
  const recon = (manifest.reconciliation ?? {}) as Record<string, unknown>;
  const signature = (manifest.signature ?? {}) as Record<string, unknown>;
  const tone = STATUS_TONE[v.status as keyof typeof STATUS_TONE] ?? "orange";

  return (
    <div className="min-h-screen bg-white">
      <header className="border-b border-[#e5e5e5]">
        <div className="mx-auto flex max-w-[1000px] items-center justify-between gap-4 px-6 py-3.5">
          <Link href="/">
            <Logo />
          </Link>
          <Link
            href="/verify"
            className="rounded-[8px] border border-[#e5e5e5] px-4 py-1.5 text-[14px] font-medium hover:bg-[#f5f5f5]"
          >
            How to verify
          </Link>
        </div>
      </header>

      <main className="mx-auto max-w-[1000px] px-6 py-8">
        <div className="mb-6">
          <p className="text-[12px] font-medium tracking-wide text-[#2563eb] uppercase">
            Public proof
          </p>
          <h1 className="mt-1.5 text-[30px] leading-tight font-semibold text-[#171717]">
            {proof.incident_id}
          </h1>
          <p className="mt-2 max-w-[70ch] text-[15px] leading-relaxed text-[#525252]">
            This manifest carries the full authoritative state snapshot. The verification
            below was recomputed from that snapshot just now, using the same Safety Kernel
            the production services used. No model, no network.
          </p>
        </div>

        <div className="mb-4 flex flex-wrap items-center gap-2">
          <Badge tone={tone} dot>
            {v.status}
          </Badge>
          <Badge tone="neutral">
            incident {String(manifest.incident_state ?? "unknown")}
          </Badge>
          <Badge tone={manifest.invariants_all_hold ? "green" : "red"}>
            {manifest.invariants_all_hold ? "all invariants hold" : "invariant failures"}
          </Badge>
          <Badge tone="orange">synthetic data</Badge>
          <Badge tone="orange">simulated field events</Badge>
        </div>

        <div className="space-y-4">
          <Card padded={false}>
            <CardHeader
              title="Verification checks"
              subtitle="Every check that could be performed, and every one that could not"
            />
            <Table headers={["", "Check", "Detail"]} minWidth={720}>
              {v.checks.map((c) => (
                <tr key={c.name}>
                  <Td className="w-[70px]">
                    <Badge
                      tone={c.result === "PASS" ? "green" : c.result === "FAIL" ? "red" : "neutral"}
                      dot={c.result !== "SKIP"}
                    >
                      {c.result}
                    </Badge>
                  </Td>
                  <Td className="font-medium whitespace-nowrap">{c.name}</Td>
                  <Td className="text-[13px] text-[#525252]">{c.detail}</Td>
                </tr>
              ))}
            </Table>
            {v.divergences.length > 0 ? (
              <div className="border-t border-[#e5e5e5] bg-[#fef2f2] p-4">
                <p className="text-[13px] font-semibold text-[#991b1b]">
                  Stored verdict does not match the recomputed verdict
                </p>
                <ul className="mt-1.5 space-y-0.5">
                  {v.divergences.map((d) => (
                    <li key={d} className="text-[13px] text-[#991b1b]">
                      {d}
                    </li>
                  ))}
                </ul>
              </div>
            ) : null}
          </Card>

          <div className="grid gap-4 md:grid-cols-2">
            <Card padded={false}>
              <CardHeader title="Reconciliation" subtitle="Every impacted container, once" />
              <div className="p-4">
                <dl className="space-y-1.5 text-[13px]">
                  {[
                    ["Total impacted", (recon.total as number) ?? 0],
                    ["Committed", ((recon.committed as string[]) ?? []).length],
                    ["Quarantined", ((recon.quarantined as string[]) ?? []).length],
                    ["In flight", ((recon.in_flight as string[]) ?? []).length],
                    ["Unresolved", ((recon.unresolved as string[]) ?? []).length],
                  ].map(([label, value]) => (
                    <div key={String(label)} className="flex justify-between gap-3">
                      <dt className="text-[#737373]">{label}</dt>
                      <dd className="mono text-[#171717]">{String(value)}</dd>
                    </div>
                  ))}
                  <div className="flex justify-between gap-3 border-t border-[#e5e5e5] pt-1.5">
                    <dt className="text-[#737373]">Complete</dt>
                    <dd>
                      <Badge tone={recon.complete ? "green" : "orange"}>
                        {recon.complete ? "yes" : "no"}
                      </Badge>
                    </dd>
                  </div>
                </dl>
              </div>
            </Card>

            <Card padded={false}>
              <CardHeader title="Signature" subtitle="Detached, over canonical JSON" />
              <div className="space-y-1.5 p-4 text-[13px]">
                {[
                  ["Backend", String(signature.backend ?? manifest.signer_backend ?? "none")],
                  ["Algorithm", String(signature.algorithm ?? "none")],
                  ["Manifest hash", String(proof.manifest_hash ?? "—").slice(0, 24) + "…"],
                  ["Model", String(manifest.model_id ?? "—")],
                  ["ADK", String(manifest.adk_version ?? "—")],
                  ["Commit", String(manifest.source_commit ?? "—")],
                  ["Environment", String(manifest.deployment_env ?? "—")],
                ].map(([label, value]) => (
                  <div key={label} className="flex justify-between gap-3">
                    <span className="text-[#737373]">{label}</span>
                    <Mono className="text-right break-all">{value}</Mono>
                  </div>
                ))}
                {proof.gcs_uri ? (
                  <div className="flex justify-between gap-3 border-t border-[#e5e5e5] pt-1.5">
                    <span className="text-[#737373]">Cloud Storage</span>
                    <Mono className="text-right break-all">{proof.gcs_uri}</Mono>
                  </div>
                ) : null}
              </div>
            </Card>
          </div>

          <Card padded={false}>
            <CardHeader
              title="Invariants"
              subtitle="Left: what the manifest claims. Right: what recomputation produced."
            />
            <Table headers={["Invariant", "Stored", "Recomputed", ""]} minWidth={520}>
              {Object.keys(v.recomputed_invariants).map((name) => {
                const stored = v.stored_invariants[name];
                const got = v.recomputed_invariants[name];
                return (
                  <tr key={name}>
                    <Td>
                      <Mono className="font-medium text-[#171717]">{name}</Mono>
                    </Td>
                    <Td>
                      <Badge tone={stored ? "green" : "red"}>{String(stored ?? "—")}</Badge>
                    </Td>
                    <Td>
                      <Badge tone={got ? "green" : "red"}>{String(got)}</Badge>
                    </Td>
                    <Td>
                      {stored === got ? (
                        <span className="text-[13px] text-[#16a34a]">match</span>
                      ) : (
                        <span className="text-[13px] font-medium text-[#dc2626]">diverges</span>
                      )}
                    </Td>
                  </tr>
                );
              })}
            </Table>
          </Card>

          <Card>
            <h2 className="text-[14px] font-semibold text-[#171717]">Verify it yourself</h2>
            <pre className="mono scroll-x mt-2.5 rounded-[8px] border border-[#e5e5e5] bg-[#f5f5f5] px-3 py-2.5 text-[12px] text-[#171717]">
              python -m nightshift.verify --manifest evidence/incidents/{proof.incident_id}
              .manifest.json
            </pre>
            <p className="mt-2.5 text-[13px] leading-relaxed text-[#525252]">
              Exit code 0 for PASS, 1 for MISMATCH, 2 for PARTIAL. The verifier rebuilds the
              world from the snapshot and re-runs the same invariant functions the services
              ran. If someone edits the snapshot to make a partial rescue look complete, the
              artifact hash fails and the recomputed verdict diverges. Both are reported
              separately so you can see which happened.
            </p>
          </Card>
        </div>
      </main>
    </div>
  );
}
