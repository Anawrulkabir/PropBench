import { describe, expect, it } from "vitest";
import worker from "../../../worker/tests/data/cf3i/cf3i_viscosity.json";
import { cf3iExample } from "./examples";
import here from "./examples/cf3i_viscosity.json";

describe("CF3I example", () => {
  it("is an exact copy of the worker's published test data", () => {
    expect(here).toEqual(worker);
  });

  it("builds SI datasets: 24 + 21 + 18 points, saturated liquid without pressures", () => {
    const ex = cf3iExample();
    expect(ex.map((e) => [e.dataset.name, e.dataset.values.length, e.saturation])).toEqual([
      ["tuhin2024_liquid", 24, null],
      ["tuhin2024_vapor", 21, null],
      ["duan1999_satliq", 18, "liquid"],
    ]);
    const liquid = ex[0].dataset;
    expect(liquid.pressure?.[0]).toBeCloseTo(3.999e6, 6);
    expect(liquid.values[0]).toBeCloseTo(208.82e-6, 15);
    expect(liquid.expanded_uncertainty?.[0]).toBeCloseTo(208.82e-6 * 0.0222, 15);
    expect(ex[2].dataset.pressure).toBeNull();
    expect(ex[2].dataset.provenance.doi).toBe("10.1016/S0378-3812(99)00216-2");
  });
});
