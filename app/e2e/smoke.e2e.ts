// GUI smoke tests (README M3): every screen opens, and the CF3I tutorial can be completed from its panel alone.
import { expect, idle, menu, test } from "./fixtures";

test("the guided CF3I tutorial can be completed from its panel alone", async ({ app }) => {
  await menu(app, "Help", "CF3I tutorial (guided)");
  const panel = app.getByRole("complementary", { name: "CF3I tutorial" });
  await expect(panel).toBeVisible();
  const seen: string[] = [];
  // Follow the panel as a new user would: press the current step's button until every step is done.
  for (let i = 0; i < 12 && !(await panel.getByText("All steps done").count()); i++) {
    const now = panel.locator("li.now");
    const title = (await now.locator(".title").textContent()) ?? "";
    seen.push(title);
    await now.getByRole("button").click();
    await idle(app);
    if (title.includes("publication figure")) {
      const download = app.waitForEvent("download");
      await app.locator(".details button.default").click(); // Export (PDF by default)
      expect((await download).suggestedFilename()).toMatch(/\.pdf$/);
    }
  }
  await expect(panel.getByText("All steps done")).toBeVisible();
  expect(seen.length).toBeGreaterThanOrEqual(7);
  // the steps did real work: the consistency check found the published overlap at 333 K
  await expect(app.getByText(/overlap at 33[23]/).first()).toBeAttached();
});

test("calculator reproduces the M0 acceptance value", async ({ app }) => {
  await menu(app, "Tools", "Property calculator");
  await app.getByRole("button", { name: "Calculate" }).click();
  await expect(app.locator("output.acceptance")).toContainText("1201.53");
});

test("uncertainty budget reproduces JCGM 100 example H.1", async ({ app }) => {
  await menu(app, "Tools", "Uncertainty budget (GUM)");
  await app.getByRole("button", { name: /Load JCGM 100/ }).click();
  await app.getByRole("button", { name: "GUM (linear)" }).click();
  await expect(app.locator(".result")).toContainText("y = 50.000838 mm");
  await expect(app.locator(".result")).toContainText("k = 2.92");
});

test("every screen and dialog opens without errors", async ({ app }) => {
  await menu(app, "Help", "Load CF3I example data");
  await idle(app);
  const views: [string, string | RegExp][] = [
    ["View", "Data check"],
    ["View", "Data consistency"],
    ["View", "Deviations"],
    ["View", "Models"],
    ["View", "Study setup"],
    ["View", "Results"],
    ["Data", "Open worksheet"],
    ["Tools", "Graph studio"],
    ["Tools", "General curve fit"],
    ["Tools", "Code and terminal"],
    ["Tools", "3D surface"],
    ["Tools", "Experiment planner"],
    ["Tools", "Setup builder"],
    ["Tools", "CAD & simulation"],
  ];
  for (const [top, item] of views) {
    await menu(app, top, item);
    await expect(app.locator(".work")).toBeVisible();
  }
  for (const [top, item] of [["File", "Settings…"], ["Tools", "Components…"], ["Tools", "Add-ons…"], ["Tools", "References…"], ["Help", "About PropBench"]]) {
    await menu(app, top, item);
    await expect(app.getByRole("dialog")).toBeVisible();
    await app.keyboard.press("Escape");
    if (await app.getByRole("dialog").count()) await app.getByRole("dialog").getByRole("button", { name: /Close|Cancel|OK/ }).last().click();
  }
});

test("a fitted ECS model exports to CoolProp with identical values and a report is generated", async ({ app }) => {
  await menu(app, "Help", "CF3I tutorial (guided)");
  const panel = app.getByRole("complementary", { name: "CF3I tutorial" });
  for (const step of ["Load data", "Check consistency", "Add ECS (R134a)", "Fit"]) {
    const button = panel.getByRole("button", { name: step });
    if (await button.count()) {
      await button.click();
      await idle(app);
    }
  }
  await menu(app, "Report", "Export to CoolProp…");
  await app.getByRole("button", { name: "Export and verify" }).click();
  await expect(app.getByText(/^Identical: largest relative difference/)).toBeVisible();
  await app.getByRole("dialog").getByRole("button", { name: "Close", exact: true }).last().click();
  await menu(app, "Report", "Generate report…");
  const download = app.waitForEvent("download");
  await app.getByRole("button", { name: "Generate" }).click();
  expect((await download).suggestedFilename()).toMatch(/-report\.pdf$/);
});
