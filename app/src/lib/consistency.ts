// Summaries of a consistency report for display (pure; the analysis itself runs in the worker).

import type { ConsistencyResponse, IsothermPlot, OffsetResult } from "./types";

export interface CheckRow {
  check: string;
  result: string;
  ok: boolean | null; // null: informational / warning
}

export function plotLabel(p: IsothermPlot): string {
  const phase = p.phase === "any" ? "" : `, ${p.phase}`;
  return `${p.other} vs trend of ${p.reference} at ${p.temperature.toFixed(2)} K${phase}`;
}

/** Range text like "5.1–8.9 %" (or a single value). */
export function rangeText(values: number[], decimals = 1, unit = " %"): string {
  if (values.length === 0) return "–";
  const lo = Math.min(...values);
  const hi = Math.max(...values);
  const f = (v: number) => (v >= 0 ? "+" : "") + v.toFixed(decimals);
  return lo === hi ? `${f(lo)}${unit}` : `${f(lo)} to ${f(hi)}${unit}`;
}

/** The checks table for the pair (reference ← other): model-free first, then model-based. */
export function pairChecks(report: ConsistencyResponse, reference: string, other: string): CheckRow[] {
  const rows: CheckRow[] = [];
  const trends = report.trend_checks.filter((t) => t.a === reference && t.b === other);
  if (trends.length) {
    const failed = trends.filter((t) => !t.passed);
    rows.push({
      check: "Pressure trend at equal T",
      result: failed.length ? `fails at ${failed.map((t) => `${t.temperature.toFixed(1)} K`).join(", ")}` : "passes",
      ok: failed.length === 0,
    });
  }
  const comps = report.comparisons.filter((c) => c.a === reference && c.b === other);
  if (comps.length) {
    const inconsistent = comps.filter((c) => !c.consistent).length;
    const extrapolated = comps.filter((c) => c.extrapolated).length;
    rows.push({
      check: "Model-free difference",
      result: rangeText(comps.map((c) => c.difference), 2),
      ok: inconsistent === 0,
    });
    rows.push({
      check: "Combined expanded uncertainty",
      result: rangeText(comps.map((c) => c.u_combined), 2, " %").replace(/\+/g, "±"),
      ok: null,
    });
    rows.push({
      check: "Points outside the combined uncertainty",
      result: `${inconsistent} of ${comps.length}`,
      ok: inconsistent === 0,
    });
    if (extrapolated) {
      rows.push({ check: "Trend values extrapolated in pressure", result: `${extrapolated} of ${comps.length}`, ok: null });
    }
  }
  const offset = report.offsets.find((o) => o.dataset === other && o.reference === reference);
  if (offset) {
    rows.push({
      check: `Offset of ${other} (model-free)`,
      result: `${offsetText(offset)} [${offset.ci95_total.map((v) => v.toFixed(1)).join(", ")}] %`,
      ok: !offset.significant,
    });
  }
  const vsModels = report.offsets.filter((o) => o.dataset === other && report.models.includes(o.reference));
  if (vsModels.length) {
    rows.push({ check: `Offset of ${other} vs models`, result: rangeText(vsModels.map((o) => o.offset)), ok: null });
  }
  return rows;
}

export function offsetText(o: OffsetResult): string {
  return `${o.offset >= 0 ? "+" : ""}${o.offset.toFixed(2)} %`;
}
