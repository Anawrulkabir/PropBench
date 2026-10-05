import { describe, expect, it } from "vitest";
import { densityRequest, errorMessage } from "./api";
import { formatValue, mpaToPa, paToMpa } from "./units";

describe("units", () => {
  it("converts MPa to Pa and back", () => {
    expect(mpaToPa(1)).toBe(1e6);
    expect(paToMpa(mpaToPa(0.101325))).toBeCloseTo(0.101325, 15);
  });

  it("formats the acceptance density to two decimals", () => {
    expect(formatValue(1201.5290150541637)).toBe("1201.53");
  });
});

describe("densityRequest", () => {
  it("builds the SI request for R134a at 300 K and 1 MPa", () => {
    expect(densityRequest(" R134a ", "300", "1")).toEqual({
      ok: true,
      request: { fluid: "R134a", pair: "PT_INPUTS", values: [1e6, 300], output: "Dmass" },
    });
  });

  it.each([
    ["", "300", "1", /fluid/],
    ["R134a", "", "1", /Temperature/],
    ["R134a", "abc", "1", /Temperature/],
    ["R134a", "-5", "1", /Temperature/],
    ["R134a", "300", "0", /Pressure/],
    ["R134a", "300", "Infinity", /Pressure/],
  ])("rejects fluid=%j T=%j p=%j", (fluid, t, p, message) => {
    const result = densityRequest(fluid, t, p);
    expect(result.ok).toBe(false);
    if (!result.ok) expect(result.error).toMatch(message);
  });
});

describe("errorMessage", () => {
  it("reads command errors and plain strings", () => {
    expect(errorMessage({ kind: "rpc", message: "unknown fluid" })).toBe("unknown fluid");
    expect(errorMessage("boom")).toBe("boom");
  });
});
