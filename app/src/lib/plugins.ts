// Plug-ins (README §2f): what the manager shows and what the user approves. The shell (pb-plugin) verifies packages
// and enforces permissions; this module only formats them and builds the approval text, so the exact permissions
// the user saw are the ones approved (the approval is bound to the package digest).

export type Signer = { status: "trusted"; key: string } | { status: "untrusted"; key: string } | { status: "unsigned" };

export interface PluginPackage {
  id: string;
  name: string;
  version: string;
  runtime: "wasm" | "python";
  kind: string;
  digest: string;
  signer: Signer;
  permissions: string[];
  reference: string;
}

export interface Installed {
  manifest: { id: string; name: string; version: string; kind: string; runtime: "wasm" | "python"; description: string; reference: string; license: string };
  digest: string;
  signer: Signer;
  approved: boolean;
  permissions: string[];
  problem: string | null;
}

export interface CheckResult {
  check: { temperature: number; molar_density: number; expected: number; rel_tol: number; source: string };
  value: number;
  rel_dev: number;
  pass: boolean;
}

export function signerLabel(s: Signer): string {
  if (s.status === "trusted") return `signed by trusted key ${s.key}`;
  if (s.status === "untrusted") return `signed by unknown key ${s.key}`;
  return "unsigned (local development)";
}

export function runsAs(runtime: string): string {
  return runtime === "wasm" ? "sandboxed (WASM)" : "Python, in the project environment";
}

/** The text of the approval prompt: everything the plug-in may do, and that everything else is denied. */
export function approvalText(p: Pick<PluginPackage, "id" | "name" | "version" | "runtime" | "signer" | "permissions" | "digest">): string {
  const lines = [
    `${p.name} ${p.version} (${p.id})`,
    `Runs as: ${runsAs(p.runtime)}`,
    `Package: ${signerLabel(p.signer)}, digest ${p.digest.slice(0, 16)}…`,
    "",
    "It may:",
    ...p.permissions.map((x) => `  • ${x}`),
    "",
    "Anything not listed is denied. Approve these permissions?",
  ];
  if (p.signer.status === "unsigned") lines.push("", "This package is not signed: approve it only if you made it or trust where it came from.");
  if (p.runtime === "python") lines.push("", "Python plug-ins are guarded, not sandboxed: install only plug-ins you trust (prefer WASM for third-party code).");
  return lines.join("\n");
}

export function verifiedLabel(results: CheckResult[] | undefined): string {
  if (!results) return "not checked";
  if (!results.length) return "no check values";
  const passed = results.filter((r) => r.pass).length;
  return passed === results.length ? `⛉ verified (${passed}/${results.length} check values)` : `failed ${results.length - passed} of ${results.length} check values`;
}
