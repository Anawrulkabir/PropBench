import { describe, expect, it } from "vitest";
import { approvalText, type CheckResult, signerLabel, verifiedLabel } from "./plugins";

const pkg = {
  id: "sutherland-air",
  name: "Sutherland viscosity of air",
  version: "1.0.0",
  runtime: "wasm" as const,
  signer: { status: "unsigned" as const },
  permissions: ["no network access", "read the project folder data/", "at most 5 s and 16 MB per run"],
  digest: "0123456789abcdef0123456789abcdef",
};

describe("plug-in approval", () => {
  it("shows every permission, denies the rest and warns about unsigned packages", () => {
    const text = approvalText(pkg);
    for (const p of pkg.permissions) expect(text).toContain(p);
    expect(text).toContain("Anything not listed is denied");
    expect(text).toContain("not signed");
    expect(text).toContain("0123456789abcdef…");
    expect(approvalText({ ...pkg, signer: { status: "trusted", key: "ABCD" } })).not.toContain("not signed");
    expect(approvalText({ ...pkg, runtime: "python" })).toContain("guarded, not sandboxed");
  });

  it("labels signers and check-value results", () => {
    expect(signerLabel({ status: "untrusted", key: "K" })).toContain("unknown key K");
    const r = (pass: boolean): CheckResult => ({ check: { temperature: 300, molar_density: 0, expected: 1, rel_tol: 0.01, source: "s" }, value: 1, rel_dev: 0, pass });
    expect(verifiedLabel(undefined)).toBe("not checked");
    expect(verifiedLabel([r(true), r(true)])).toContain("verified (2/2");
    expect(verifiedLabel([r(true), r(false)])).toBe("failed 1 of 2 check values");
  });
});
