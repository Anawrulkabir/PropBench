import { describe, expect, it } from "vitest";
import { currentStep, STEPS, type TutorialState } from "./tutorial";

const empty: TutorialState = {
  datasets: [],
  checks: {},
  consistency: null,
  candidates: [],
  locked: null,
  comparison: null,
  log: [],
  filePath: null,
};

describe("CF3I tutorial", () => {
  it("starts at the first step and advances with the project state", () => {
    expect(currentStep(empty)).toBe(0);
    const s: TutorialState = { ...empty, datasets: [{ name: "a" }, { name: "b" }, { name: "c" }], checks: { a: {} } };
    expect(STEPS[currentStep(s)].id).toBe("consistency");
  });

  it("counts steps done through the menus and finishes", () => {
    const done: TutorialState = {
      datasets: [{ name: "a" }, { name: "b" }, { name: "c" }],
      checks: { a: {} },
      consistency: {},
      candidates: [{ start: { kind: "ecs_viscosity" }, fit: {}, study: {} }],
      locked: { sha256: "x" },
      comparison: {},
      log: [{ text: "Figure exported as PDF (Elsevier)" }],
      filePath: "/x/cf3i.pbp",
    };
    expect(currentStep(done)).toBe(STEPS.length);
    expect(STEPS[currentStep({ ...done, locked: null })].id).toBe("validate");
  });
});
