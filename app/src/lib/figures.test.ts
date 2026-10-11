import { describe, expect, it } from "vitest";
import { deviationPlot, propertyPlot, stateMap } from "./figures";
import type { Dataset } from "./types";

const ds = {
  name: "d",
  fluid: "R13I1",
  quantity: "viscosity",
  temperature: [300, 320],
  values: [2e-4, 1.8e-4],
  pressure: [3e6, 4e6],
  expanded_uncertainty: [4e-6, 3.6e-6],
} as unknown as Dataset;

describe("standard figure specs", () => {
  it("state map in MPa and property plot with error bars in display units", () => {
    expect(stateMap([ds]).layers[0]).toMatchObject({ type: "points", name: "d", y: [3, 4] });
    const p = propertyPlot([ds], { symbol: "η", unit: "µPa·s", factor: 1e6 });
    expect(p.y.label).toBe("η / µPa·s");
    expect(p.layers[0]).toMatchObject({ y: [200, 180] });
  });

  it("deviation plot groups points by dataset with a zero line", () => {
    const spec = deviationPlot({ dataset: ["a", "b", "a"], temperature: [1, 2, 3], ard: [0.1, -0.2, 0.3] }, "ECS", { symbol: "η", unit: "", factor: 1 });
    expect(spec.layers).toHaveLength(3);
    expect(spec.layers[1]).toMatchObject({ name: "a", x: [1, 3], y: [0.1, 0.3] });
  });
});
