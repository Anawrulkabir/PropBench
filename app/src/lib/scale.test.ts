import { afterEach, describe, expect, it, vi } from "vitest";
import { loadScale, SCALES } from "./scale";

describe("text scale", () => {
  afterEach(() => vi.unstubAllGlobals());

  it("falls back to 100 % without storage", () => {
    vi.stubGlobal("localStorage", undefined);
    expect(loadScale()).toBe(100);
  });

  it("accepts only the offered sizes", () => {
    const store: Record<string, string> = { "propbench.scale": "125" };
    vi.stubGlobal("localStorage", { getItem: (k: string) => store[k] ?? null });
    expect(loadScale()).toBe(125);
    store["propbench.scale"] = "37";
    expect(loadScale()).toBe(100);
    expect(SCALES).toContain(100);
  });
});
