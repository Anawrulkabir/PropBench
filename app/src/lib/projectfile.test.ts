import { describe, expect, it } from "vitest";
import {
  addSnapshot,
  fingerprint,
  fromContent,
  restoreSnapshot,
  type ProjectContent,
  type SavedState,
  toContent,
} from "./projectfile";
import type { Dataset } from "./types";

function dataset(name: string, values: number[]): Dataset {
  return {
    schema_version: 1,
    name,
    fluid: "R13I1",
    quantity: "viscosity",
    temperature: values.map((_, i) => 300 + i),
    values,
    point_ids: values.map((_, i) => i),
    pressure: null,
    molar_density: null,
    expanded_uncertainty: null,
    coverage_factor: 2,
    phase: null,
    provenance: { doi: null, citation: null, method: null, notes: "" },
  } as unknown as Dataset;
}

function state(): SavedState {
  return {
    name: "CF3I",
    datasets: [dataset("a", [1e-4, 2e-4]), dataset("b", [3e-4])],
    checks: {},
    candidates: [],
    settings: { seed: 2026, methods: ["lostate"] },
    rule: { metric: "cv_aard", validation: "lostate", tie_tolerance: 0.05, require_physics: true, notes: "" },
    locked: null,
    selection: null,
    masks: { a: [1] },
    consistency: null,
    comparison: null,
    consistencySettings: { tTol: 1, references: true },
    scripts: { "fit.py": "print(1)\n" },
    environment: { packages: [], lock: "" },
    worksheets: {},
    tools: { curvefits: [], budgets: [], references: [] },
  };
}

describe("project file content", () => {
  it("round-trips the saved state", () => {
    const s = state();
    const content = toContent(s, null, [{ time: 1, action: "import", detail: "a, b" }]);
    expect(content.datasets.map((d) => d.name)).toEqual(["a", "b"]);
    expect(content.audit).toHaveLength(1);
    const back = fromContent(JSON.parse(JSON.stringify(content)) as ProjectContent, state());
    expect(fingerprint(back)).toBe(fingerprint(s));
  });

  it("keeps creation time, snapshots, audit and unknown documents of the previous file", () => {
    const first = addSnapshot(toContent(state(), null, []), "imported");
    first.documents["future_feature"] = { x: 1 };
    const created = first.meta.created;
    const s = state();
    s.name = "renamed";
    const second = toContent(s, first, [{ time: 2, action: "rename", detail: "" }]);
    expect(second.meta.created).toBe(created);
    expect(second.meta.name).toBe("renamed");
    expect(second.snapshots).toHaveLength(1);
    expect(second.documents["future_feature"]).toEqual({ x: 1 });
    expect(second.audit.map((a) => a.action)).toEqual(["snapshot", "rename"]);
  });

  it("restores a snapshot and fills missing documents with defaults", () => {
    let content = toContent(state(), null, []);
    content = addSnapshot(content, "two datasets");
    content = { ...content, datasets: content.datasets.slice(0, 1) };
    const restored = restoreSnapshot(content, 1);
    expect(restored.datasets).toHaveLength(2);
    expect(() => restoreSnapshot(content, 9)).toThrow("no snapshot 9");
    delete restored.documents["masks"];
    expect(fromContent(restored, { ...state(), masks: {} }).masks).toEqual({});
  });

  it("detects changes through the fingerprint", () => {
    const s = state();
    const before = fingerprint(s);
    s.masks = { a: [0, 1] };
    expect(fingerprint(s)).not.toBe(before);
  });
});
