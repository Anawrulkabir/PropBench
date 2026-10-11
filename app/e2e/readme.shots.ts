// README screenshots of the real app (built UI + real Python worker, see fixtures.ts), after the CF3I tutorial steps.
//   npm run build && npm run screenshots   → ../docs/images/app/*.png
import path from "node:path";
import { fileURLToPath } from "node:url";
import { expect, idle, menu, test } from "./fixtures";

const out = path.join(path.dirname(fileURLToPath(import.meta.url)), "..", "..", "docs", "images", "app");

test("README screenshots", async ({ app }) => {
  const shot = async (name: string) => {
    await idle(app);
    await app.waitForTimeout(600);
    await app.screenshot({ path: path.join(out, `${name}.png`) });
  };
  await menu(app, "Help", "CF3I tutorial (guided)");
  const panel = app.getByRole("complementary", { name: "CF3I tutorial" });
  for (let i = 0; i < 12 && !(await panel.getByText("All steps done").count()); i++) {
    const now = panel.locator("li.now");
    const title = (await now.locator(".title").textContent()) ?? "";
    if (title.includes("publication figure")) break;
    await now.getByRole("button").click();
    await idle(app);
    if (i === 1) await shot("tutorial");
  }
  await app.getByRole("button", { name: "Close the tutorial" }).click();
  for (const [name, top, item] of [
    ["data-check", "View", "Data check"],
    ["deviations", "View", "Deviations"],
    ["results", "View", "Results"],
    ["worksheet", "Data", "Open worksheet"],
    ["graph-studio", "Tools", "Graph studio"],
    ["curve-fit", "Tools", "General curve fit"],
    ["code", "Tools", "Code and terminal"],
  ] as const) {
    await menu(app, top, item);
    if (name === "curve-fit") {
      await app.locator(".work").getByRole("button", { name: "Fit", exact: true }).click();
      await expect(app.locator(".work").getByRole("button", { name: "Fit", exact: true })).toBeEnabled();
    }
    await shot(name);
  }
  await menu(app, "Tools", "Property calculator");
  await app.getByRole("button", { name: "Calculate" }).click();
  await shot("calculator");
});
