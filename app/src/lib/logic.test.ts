import { describe, expect, it } from "vitest";
import { buildMapping, guessColumn } from "./mapping";
import { breakAtPhaseChange, fixedScale, linearScale, niceTicks, tickLabel } from "./plot";
import { display, fmt, pct, withError } from "./quantities";
import {
  applyMask,
  pointSeries,
  type Candidate,
  candidateMetrics,
  commonTarget,
  deviationSeries,
  freeParameters,
  selectionCandidates,
  typicalUncertainty,
  uniqueName,
} from "./study";
import type { Dataset, FitResponse, ModelSpec, StudyResponse } from "./types";

describe("guessColumn", () => {
  it.each([
    ["T [K]", "temperature", "K"],
    ["T/°C", "temperature", "degC"],
    ["Temperature (K)", "temperature", "K"],
    ["p [MPa]", "pressure", "MPa"],
    ["P (kPa)", "pressure", "kPa"],
    ["pressure/bar", "pressure", "bar"],
    ["eta [µPa·s]", "value", "uPa*s"],
    ["η (mPa s)", "value", "mPa*s"],
    ["viscosity", "value", "uPa*s"],
    ["phase", "phase", ""],
    ["rho [mol/L]", "molar_density", "mol/L"],
    ["comment", "ignore", ""],
  ])("%s → %s %s", (header, role, unit) => {
    const g = guessColumn(header, "viscosity");
    expect(g.role).toBe(role);
    expect(g.unit).toBe(unit);
  });

  it("recognises relative uncertainty columns", () => {
    expect(guessColumn("U (%)", "viscosity")).toEqual({ role: "uncertainty", unit: "", uncertaintyKind: "relative_percent" });
    expect(guessColumn("u", "viscosity").uncertaintyKind).toBe("absolute");
  });
});

describe("buildMapping", () => {
  const headers = ["T", "p", "eta", "U", "note"];
  const choices = [
    { role: "temperature", unit: "K", uncertaintyKind: "" },
    { role: "pressure", unit: "MPa", uncertaintyKind: "" },
    { role: "value", unit: "uPa*s", uncertaintyKind: "" },
    { role: "uncertainty", unit: "", uncertaintyKind: "relative_percent" },
    { role: "ignore", unit: "", uncertaintyKind: "" },
  ] as const;

  it("builds the worker's mapping and skips ignored columns", () => {
    const m = buildMapping(headers, choices.map((c) => ({ ...c })), "viscosity", 1, 2, null);
    expect(m).toEqual({
      kind: "propbench.import-mapping",
      version: 1,
      quantity: "viscosity",
      header_row: 1,
      coverage_factor: 2,
      columns: [
        { column: "T", role: "temperature", unit: "K" },
        { column: "p", role: "pressure", unit: "MPa" },
        { column: "eta", role: "value", unit: "uPa*s" },
        { column: "U", role: "uncertainty", uncertainty_kind: "relative_percent" },
      ],
    });
    expect(buildMapping(headers, choices.map((c) => ({ ...c })), "viscosity", 2, 2, "Sheet1").sheet).toBe("Sheet1");
  });

  it("explains what is missing", () => {
    const noState = choices.map((c) => ({ ...c, role: c.role === "pressure" ? "ignore" : c.role })) as never;
    expect(() => buildMapping(headers, noState, "viscosity", 1, 2, null)).toThrow(/pressure or molar-density/);
    expect(buildMapping(headers, noState, "viscosity", 1, 2, null, null, "liquid").saturation).toBe("liquid");
    const twice = choices.map((c) => ({ ...c, role: c.role === "pressure" ? "temperature" : c.role })) as never;
    expect(() => buildMapping(headers, twice, "viscosity", 1, 2, null)).toThrow(/Two columns/);
    const noValue = choices.map((c) => ({ ...c, role: c.role === "value" ? "ignore" : c.role })) as never;
    expect(() => buildMapping(headers, noValue, "viscosity", 1, 2, null)).toThrow(/property values/);
  });
});

describe("plot scales", () => {
  it("chooses 1-2-5 ticks covering the data", () => {
    expect(niceTicks(0, 10, 6)).toEqual([0, 2, 4, 6, 8, 10]);
    expect(niceTicks(251, 399, 7)).toEqual([250, 275, 300, 325, 350, 375, 400]);
    const t = niceTicks(-0.37, 0.52);
    expect(t[0]).toBeLessThanOrEqual(-0.37);
    expect(t[t.length - 1]).toBeGreaterThanOrEqual(0.52);
    expect(niceTicks(5, 5).length).toBeGreaterThan(1);
    expect(niceTicks(Number.NaN, 1)).toEqual([]);
  });

  it("maps the domain onto the range and ignores missing values", () => {
    const s = linearScale([0, null, 10, Number.NaN], [100, 200]);
    expect(s.map(0)).toBe(100);
    expect(s.map(10)).toBe(200);
    expect(linearScale([2, 3], [0, 1], 6, 0).domain[0]).toBeLessThanOrEqual(0);
  });

  it("labels ticks compactly", () => {
    expect(tickLabel(0.30000000000000004)).toBe("0.3");
    expect(tickLabel(2e-5)).toBe("2.0e-5");
    expect(tickLabel(250)).toBe("250");
  });
});

describe("display formatting", () => {
  it("converts SI values for display", () => {
    expect(display("viscosity").factor * 1.5e-4).toBeCloseTo(150, 10);
    expect(display("unknown").unit).toBe("SI");
  });

  it("formats numbers, percentages and parameter errors", () => {
    expect(fmt(null)).toBe("–");
    expect(fmt(1201.5290150541637, 6)).toBe("1201.53");
    expect(pct(0.54321)).toBe("0.54");
    expect(withError(1.13284, 0.01171)).toBe("1.133 ± 0.012");
    expect(withError(-0.0541, null)).toBe("-0.0541");
  });
});

const spec: ModelSpec = {
  kind: "ecs_viscosity",
  name: "ECS viscosity",
  fluid: "R13I1",
  quantity: "viscosity",
  reference: "Huber 2003",
  parameters: {
    psi_0: { value: 1, lower: -10, upper: 10, fixed: false, unit: "1", description: "" },
    psi_1: { value: 0, lower: -10, upper: 10, fixed: false, unit: "1", description: "" },
    k: { value: 1, lower: 0.5, upper: 2, fixed: true, unit: "1", description: "" },
  },
};

function dataset(name: string, values: number[], u: number[] | null, fluid = "R13I1"): Dataset {
  return {
    schema_version: 1,
    name,
    fluid,
    quantity: "viscosity",
    temperature: values.map((_, i) => 300 + i),
    values,
    pressure: values.map(() => 1e6),
    molar_density: null,
    expanded_uncertainty: u,
    coverage_factor: 2,
    phase: null,
    point_ids: values.map((_, i) => i),
    provenance: {},
  };
}

const fit: FitResponse = {
  model: spec,
  summary: {
    values: { psi_0: 1.1 },
    standard_errors: { psi_0: 0.01 },
    scale_factors: {},
    deviations: { n: 3, aard: 0.5, bias: 0.1, rms: 0.6, max_abs: 1 },
    cost: 1,
    success: true,
    message: "",
    nfev: 10,
    starts: 1,
    seed: 0,
    weighted: true,
  },
  criteria: { aic: -3, bic: -2 },
  n_parameters: 1,
  points: {
    dataset: ["a", "b", "a"],
    point_id: [0, 0, 1],
    temperature: [300, 310, 320],
    molar_density: [1, 2, 3],
    value: [1, 2, 3],
    ard: [0.1, null, -0.2],
  },
};

const study: StudyResponse = {
  seed: 0,
  cross_validation: {
    loso: {
      method: "loso",
      seed: 0,
      pooled: { n: 3, aard: 0.8, bias: 0, rms: 0.9, max_abs: 1.2 },
      folds: [],
      parameters: {},
    },
  },
  physics: [{ name: "extrapolation", passed: false, n_states: 3, message: "", violations: [], not_evaluated: 0 }],
};

describe("study helpers", () => {
  it("makes unique names", () => {
    expect(uniqueName(["a"], "b")).toBe("b");
    expect(uniqueName(["a", "a (2)"], "a")).toBe("a (3)");
  });

  it("requires one fluid and one property", () => {
    expect(commonTarget([])).toMatch(/Import/);
    expect(commonTarget([dataset("a", [1], null), dataset("b", [1], null, "R134a")])).toMatch(/different fluids/);
    expect(commonTarget([dataset("a", [1], null)])).toEqual({ fluid: "R13I1", quantity: "viscosity" });
  });

  it("counts free parameters with the user's fixed choices", () => {
    const c: Candidate = { id: "1", label: "ECS", start: spec, fixed: { psi_1: true, k: false }, fit: null, study: null, error: null };
    expect(freeParameters(c)).toEqual(["psi_0", "k"]);
  });

  it("reports metrics and physics for the selection rule", () => {
    const c: Candidate = { id: "1", label: "ECS", start: spec, fixed: {}, fit, study, error: null };
    expect(candidateMetrics(c, "loso")).toEqual({ cv_aard: 0.8, cv_rms: 0.9, fit_aard: 0.5, aic: -3, bic: -2 });
    expect(candidateMetrics(c, "kfold").cv_aard).toBeNull();
    expect(selectionCandidates([c], "loso")).toEqual([
      { name: "ECS", n_parameters: 1, metrics: candidateMetrics(c, "loso"), physics_passed: false },
    ]);
  });

  it("groups deviations by dataset", () => {
    expect(deviationSeries(fit)).toEqual([
      { name: "a", x: [300, 320], y: [0.1, -0.2] },
      { name: "b", x: [310], y: [null] },
    ]);
  });

  it("finds the median relative expanded uncertainty", () => {
    expect(typicalUncertainty([dataset("a", [100, 200, 400], [1, 4, 12])])).toBeCloseTo(2, 12);
    expect(typicalUncertainty([dataset("a", [1], null)])).toBeNull();
  });
});

describe("masking", () => {
  it("drops masked points from every array and keeps their ids", () => {
    const d = dataset("a", [1, 2, 3], [0.1, 0.2, 0.3]);
    const m = applyMask(d, [1]);
    expect(m.point_ids).toEqual([0, 2]);
    expect(m.values).toEqual([1, 3]);
    expect(m.temperature).toEqual([300, 302]);
    expect(m.pressure).toEqual([1e6, 1e6]);
    expect(m.expanded_uncertainty).toEqual([0.1, 0.3]);
    expect(m.molar_density).toBeNull();
    expect(applyMask(d, [])).toBe(d);
    expect(applyMask(d, [0, 1, 2]).values).toEqual([]);
  });
});

describe("pointSeries", () => {
  it("maps point ids to temperatures and groups by dataset", () => {
    const a = dataset("a", [1, 2, 3], null);
    const b = dataset("b", [5], null);
    expect(pointSeries([a, b], ["a", "b", "a", "x"], [2, 0, 0, 0], [0.1, -0.2, 0.3, 9])).toEqual([
      { name: "a", x: [302, 300], y: [0.1, 0.3] },
      { name: "b", x: [300], y: [-0.2] },
    ]);
  });
});

describe("graph helpers", () => {
  it("breaks an isobar at the liquid-vapour jump", () => {
    expect(breakAtPhaseChange([200, 190, 180, 20, 21, null, 22])).toEqual([200, 190, 180, null, 21, null, 22]);
  });

  it("keeps a user-set axis range", () => {
    const s = fixedScale([250, 400], [0, 100]);
    expect(s.domain).toEqual([250, 400]);
    expect(s.map(325)).toBe(50);
    expect(s.ticks[0]).toBeGreaterThanOrEqual(250);
    expect(s.ticks[s.ticks.length - 1]).toBeLessThanOrEqual(400);
  });
});

describe("turbo colour map", () => {
  it("runs from dark blue through green to dark red and clamps", async () => {
    const { turbo } = await import("./surface");
    expect(turbo(0)).toBe("rgb(35, 23, 27)");
    expect(turbo(-1)).toBe(turbo(0));
    expect(turbo(2)).toBe(turbo(1));
    const mid = turbo(0.5).match(/\d+/g)?.map(Number) ?? [];
    expect(mid[1]).toBeGreaterThan(mid[0]);
    expect(mid[1]).toBeGreaterThan(mid[2]);
  });
});

describe("measuredStates", () => {
  it("groups repeats by temperature and pressure", async () => {
    const { measuredStates } = await import("./study");
    const d = dataset("lab", [208.82, 208.67, 209.69, 203.71], null);
    d.temperature = [332.96, 332.97, 332.85, 332.83];
    d.pressure = [3.999e6, 3.999e6, 4.002e6, 3.0e6];
    const states = measuredStates(d);
    expect(states.map((s) => s.rows)).toEqual([[0, 1, 2], [3]]);
    expect(states[0].mean).toBeCloseTo((208.82 + 208.67 + 209.69) / 3, 10);
    expect(states[0].spread).toBeCloseTo(1.02, 10);
    expect(states[0].temperature).toBeCloseTo(332.9267, 4);
  });
});
