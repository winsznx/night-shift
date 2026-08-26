import Link from "next/link";

import { Logo } from "@/components/shell";
import { Badge, Card, CardHeader, Mono, Table, Td } from "@/components/ui";
import { getEvidence } from "@/lib/api";

export const revalidate = 30;

export default async function VerifyPage() {
  const evidence = await getEvidence();

  return (
    <div className="min-h-screen bg-white">
      <header className="border-b border-[#e5e5e5]">
        <div className="mx-auto flex max-w-[1000px] items-center justify-between gap-4 px-6 py-3.5">
          <Link href="/"><Logo /></Link>
          <Link href="/app" className="rounded-[8px] border border-[#e5e5e5] px-4 py-1.5 text-[14px] font-medium hover:bg-[#f5f5f5]">
            Open console
          </Link>
        </div>
      </header>

      <main className="mx-auto max-w-[1000px] px-6 py-10">
        <p className="text-[12px] font-medium tracking-wide text-[#2563eb] uppercase">Verification</p>
        <h1 className="mt-1.5 max-w-[24ch] text-[30px] leading-tight font-semibold text-[#171717]">
          Check the evidence without trusting us
        </h1>
        <p className="mt-3 max-w-[70ch] text-[16px] leading-relaxed text-[#525252]">
          Every completed incident produces a canonical JSON manifest carrying the full
          authoritative state snapshot, hashed with SHA-256 and signed with a Cloud KMS
          asymmetric key. The verifier rebuilds the world from that snapshot and re-runs
          the same invariant functions the production services ran.
        </p>

        <div className="mt-8 space-y-4">
          <Card>
            <h2 className="text-[14px] font-semibold text-[#171717]">Run the verifier</h2>
            <pre className="mono scroll-x mt-2.5 rounded-[8px] border border-[#e5e5e5] bg-[#f5f5f5] px-3 py-2.5 text-[12px] leading-relaxed text-[#171717]">{`git clone <repo> && cd night-shift
make setup
make verify-demo

# or point it at any manifest, local or remote
python -m nightshift.verify --manifest evidence/incidents/<id>.manifest.json
python -m nightshift.verify --manifest https://storage.googleapis.com/<bucket>/incidents/<id>/manifest.json`}</pre>
            <p className="mt-3 text-[13px] leading-relaxed text-[#525252]">
              No model, no network beyond fetching the manifest itself, and no Google Cloud
              credentials. The deterministic reference proof runs on a clean clone.
            </p>
          </Card>

          <Card padded={false}>
            <CardHeader title="What each result means" />
            <Table headers={["Result", "Meaning", "Exit"]} minWidth={620}>
              <tr>
                <Td><Badge tone="green" dot>PASS</Badge></Td>
                <Td className="text-[13px]">Every check performed, every one passed. Signature valid, artifact hashes match, recomputed verdict identical to the stored one.</Td>
                <Td><Mono>0</Mono></Td>
              </tr>
              <tr>
                <Td><Badge tone="red" dot>MISMATCH</Badge></Td>
                <Td className="text-[13px]">Something diverged. The report names which: a hash, the signature, or a specific invariant whose stored value disagrees with recomputation.</Td>
                <Td><Mono>1</Mono></Td>
              </tr>
              <tr>
                <Td><Badge tone="orange">PARTIAL</Badge></Td>
                <Td className="text-[13px]">Everything checkable checked out, but something could not be checked — most often an unsigned manifest. Never reported as PASS.</Td>
                <Td><Mono>2</Mono></Td>
              </tr>
            </Table>
          </Card>

          <Card padded={false}>
            <CardHeader title="Published manifests" subtitle="Verified live when this page rendered" />
            {evidence?.manifests?.length ? (
              <Table headers={["Incident", "State", "Invariants", "Signer", "Verification", ""]} minWidth={780}>
                {evidence.manifests.map((m) => (
                  <tr key={m.incident_id}>
                    <Td><Mono className="font-medium text-[#171717]">{m.incident_id}</Mono></Td>
                    <Td><Badge tone={m.incident_state === "CLOSED" ? "green" : "blue"}>{m.incident_state}</Badge></Td>
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
                        Open proof
                      </Link>
                    </Td>
                  </tr>
                ))}
              </Table>
            ) : (
              <div className="px-4 py-10 text-center text-[13px] text-[#737373]">
                No manifests published yet. Run <Mono>make evidence</Mono> to generate one.
              </div>
            )}
          </Card>

          <Card>
            <h2 className="text-[14px] font-semibold text-[#171717]">What the verifier cannot tell you</h2>
            <p className="mt-1.5 max-w-[78ch] text-[13px] leading-relaxed text-[#525252]">
              It proves the stored verdict follows from the stored state, and that the state
              was signed by the holder of the published key. It does not prove the state
              describes the physical world — this is a synthetic estate and the responder
              movements are simulated. It also says nothing about the quality of the agents&apos;
              judgement, only that the deterministic rules held whatever they decided.
            </p>
          </Card>
        </div>
      </main>
    </div>
  );
}
