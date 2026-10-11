import { describe, expect, it } from "vitest";
import { loadGithub, splitRepo } from "./history";

describe("history settings", () => {
  it("parses owner/repo and has safe defaults", () => {
    expect(splitRepo("lab/cf3i-project")).toEqual({ owner: "lab", repo: "cf3i-project" });
    expect(splitRepo("lab/a/b")).toBeNull();
    expect(splitRepo("../x")).toBeNull();
    expect(loadGithub()).toMatchObject({ branch: "main", commitOnSave: true });
  });
});

describe("recorded scripts", () => {
  it("turn model labels into Python identifiers", async () => {
    const { pyName } = await import("./recording");
    expect(pyName("ECS viscosity (R134a)")).toBe("ecs_viscosity_r134a");
    expect(pyName("2-param fit")).toBe("m_2_param_fit");
  });
});
