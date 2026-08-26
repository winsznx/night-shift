import Link from "next/link";

import { AppShell, ApiDown, PageHeader } from "@/components/shell";
import { Badge, Card, CardHeader, Mono, Table, Td } from "@/components/ui";
import { getEvidence } from "@/lib/api";

export const revalidate = 30;

export default async function EvidencePage() {
  const evidence = await getEvidence();

  return (
    <AppShell active="/app/evidence">
      <PageHeader
        title="Evidence"
        subtitle="Signed manifests, the measurement campaign, and the claim ledger. Every public claim names the artifact that supports it and the command that reproduces it."
      />
      {!evidence ? (
        <ApiDown what="Evidence" />
      ) : (
        <div className="space-y-4">
          <Card padded={false}>
            <CardHeader title="Incident manifests" subtitle="Verified live when this page rendered" />
            {evidence.manifests.length === 0 ? (
              <div className="px-4 py-10 text-center text-[13px] text-[#737373]">
                No manifests yet. Run <Mono>make evidence</Mono>.
              </div>
            ) : (
              <Table headers={["Incident", "State", "Reconciled", "Invariants", "Signer", "Verification", ""]} minWidth={860}>
                {evidence.manifests.map((m) => (
                  <tr key={m.incident_id}>
                    <Td><Mono className="font-medium text-[#171717]">{m.incident_id}</Mono></Td>
                    <Td><Badge tone={m.incident_state === "CLOSED" ? "green" : "blue"}>{m.incident_state}</Badge></Td>
                    <Td>
                      <Mono>
                        {(m.reconciliation?.committed ?? []).length}/{m.reconciliation?.total ?? 0}
                      </Mono>
                    </Td>
                    <Td>
                      <Badge tone={m.invariants_all_hold ? "green" : "red"}>
                        {m.invariants_all_hold ? "all hold" : m.failed_invariants.join(", ")}
                      </Badge>
                    </Td>
                    <Td><Mono className="text-[11px]">{m.signer_backend}</Mono></Td>
                    <Td>
                      <Badge tone={m.verification_status === "PASS" ? "green" : m.verification_status === "MISMATCH" ? "red" : "orange"} dot>
                        {m.verification_status}
                      </Badge>
                    </Td>
                    <Td>
                      <Link href={`/proof/${m.incident_id}`} className="text-[13px] font-medium text-[#2563eb] hover:underline">
                        Proof
                      </Link>
                    </Td>
                  </tr>
                ))}
              </Table>
            )}
          </Card>

          <Card padded={false}>
            <CardHeader
              title="Claim ledger"
              subtitle="Nothing is claimed here that is not backed by a named artifact and a reproduction command"
            />
            {evidence.claims.length === 0 ? (
              <div className="px-4 py-10 text-center text-[13px] text-[#737373]">
                The claim ledger has not been generated yet.
              </div>
            ) : (
              <ul className="divide-y divide-[#e5e5e5]">
                {evidence.claims.map((c) => (
                  <li key={c.id} className="px-4 py-3">
                    <div className="flex flex-wrap items-center gap-2">
                      <Mono className="text-[11px]">{c.id}</Mono>
                      <Badge tone={c.status === "live" ? "green" : c.status === "local" ? "blue" : "orange"}>
                        {c.status}
                      </Badge>
                    </div>
                    <p className="mt-1.5 text-[14px] leading-snug text-[#171717]">{c.claim}</p>
                    <div className="mt-1.5 space-y-0.5 text-[12px] text-[#737373]">
                      <p>evidence: <Mono className="text-[11px]">{c.evidence}</Mono></p>
                      <p>reproduce: <Mono className="text-[11px]">{c.reproduce}</Mono></p>
                      {c.limitation ? <p className="text-[#9a3412]">limitation: {c.limitation}</p> : null}
                    </div>
                  </li>
                ))}
              </ul>
            )}
          </Card>
        </div>
      )}
    </AppShell>
  );
}
