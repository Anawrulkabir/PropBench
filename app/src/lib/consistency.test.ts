import { describe, expect, it } from "vitest";
import { offsetText, pairChecks, plotLabel, rangeText } from "./consistency";
import type { ConsistencyResponse } from "./types";

const report: ConsistencyResponse = {
  overlaps: [{ a: "lab", b: "old", t_range: [332.5, 338.2], a_points: [0], b_points: [0, 1] }],
  comparisons: [
    { a: "lab", b: "old", point_id: 0, temperature: 333, delta_t: 0, pressure: 1.2e6, value: 2.07e-4, trend_value: 1.97e-4, difference: 5.1, u_combined: 3.7, z: 2.76, consistent: false, extrapolated: true },
    { a: "lab", b: "old", point_id: 1, temperature: 333, delta_t: 0, pressure: 2.5e6, value: 2.0e-4, trend_value: 1.99e-4, difference: 0.5, u_combined: 3.6, z: 0.28, consistent: true, extrapolated: false },
  ],
  trend_checks: [{ a: "lab", b: "old", temperature: 333, slope_sign: 1, violations: [[0, 0]], passed: false }],
  offsets: [
    { dataset: "old", reference: "lab", n: 2, offset: 4.7, ci95: [3.3, 6.2], u_reference: 1.1, ci95_total: [2.5, 7.0], birge: 0.4, significant: true, extrapolated: 1 },
    { dataset: "old", reference: "ECS", n: 2, offset: 5.0, ci95: [3, 7], u_reference: 0, ci95_total: [3, 7], birge: 0.5, significant: true, extrapolated: 0 },
    { dataset: "old", reference: "RES", n: 2, offset: 9.0, ci95: [7, 11], u_reference: 0, ci95_total: [7, 11], birge: 0.5, significant: true, extrapolated: 0 },
  ],
  z_scores: [],
  warnings: [],
  models: ["ECS", "RES"],
  plots: [
    {
      temperature: 333,
      phase: "liquid",
      reference: "lab",
      other: "old",
      points: [],
      trend: { pressure: [], value: [] },
      trend_range: [2e6, 4e6],
    },
  ],
};

describe("consistency summaries", () => {
  it("labels plots and formats ranges", () => {
    expect(plotLabel(report.plots[0])).toBe("old vs trend of lab at 333.00 K, liquid");
    expect(rangeText([5, 9])).toBe("+5.0 to +9.0 %");
    expect(rangeText([-1.234], 2)).toBe("-1.23 %");
    expect(rangeText([])).toBe("–");
    expect(offsetText(report.offsets[0])).toBe("+4.70 %");
  });

  it("builds the checks table of one pair, model-free first", () => {
    const rows = pairChecks(report, "lab", "old");
    expect(rows.map((r) => r.check)).toEqual([
      "Pressure trend at equal T",
      "Model-free difference",
      "Combined expanded uncertainty",
      "Points outside the combined uncertainty",
      "Trend values extrapolated in pressure",
      "Offset of old (model-free)",
      "Offset of old vs models",
    ]);
    expect(rows[0]).toEqual({ check: "Pressure trend at equal T", result: "fails at 333.0 K", ok: false });
    expect(rows[1].result).toBe("+0.50 to +5.10 %");
    expect(rows[3]).toMatchObject({ result: "1 of 2", ok: false });
    expect(rows[5].result).toBe("+4.70 % [2.5, 7.0] %");
    expect(rows[6].result).toBe("+5.0 to +9.0 %");
    expect(pairChecks(report, "old", "lab")).toEqual([]);
  });
});
