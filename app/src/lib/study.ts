// Pure helpers for candidates, metrics and selection (unit-tested; no Svelte, no IPC).

import type { Dataset, FitResponse, ModelSpec, StudyResponse } from "./types";

export interface Candidate {
  id: string;
  label: string;
  start: ModelSpec;
  fixed: Record<string, boolean>;
  fit: FitResponse | null;
  study: StudyResponse | null;
  error: string | null;
}

/** A name not yet in `existing`: "base", then "base (2)", "base (3)", ... */
export function uniqueName(existing: Iterable<string>, base: string): string {
  const taken = new Set(existing);
  if (!taken.has(base)) return base;
  for (let i = 2; ; i++) {
    const name = `${base} (${i})`;
    if (!taken.has(name)) return name;
  }
}

/** Fluid and quantity shared by all datasets, or an error message. */
export function commonTarget(datasets: Dataset[]): { fluid: string; quantity: string } | string {
  if (datasets.length === 0) return "Import data first.";
  const fluids = new Set(datasets.map((d) => d.fluid));
  const quantities = new Set(datasets.map((d) => d.quantity));
  if (fluids.size > 1) return `The datasets are for different fluids (${[...fluids].join(", ")}).`;
  if (quantities.size > 1) return `The datasets hold different properties (${[...quantities].join(", ")}).`;
  return { fluid: datasets[0].fluid, quantity: datasets[0].quantity };
}

/** Number of free parameters after applying the candidate's fixed/free choices. */
export function freeParameters(c: Candidate): string[] {
  return Object.entries(c.start.parameters)
    .filter(([name, p]) => !(c.fixed[name] ?? p.fixed))
    .map(([name]) => name);
}

export function physicsPassed(study: StudyResponse | null): boolean | null {
  if (!study?.physics) return null;
  return study.physics.every((c) => c.passed);
}

/** Metrics for the selection rule (`propbench.validate.METRICS`); null where not computed yet. */
export function candidateMetrics(c: Candidate, validation: string): Record<string, number | null> {
  return {
    cv_aard: c.study?.cross_validation[validation]?.pooled.aard ?? null,
    cv_rms: c.study?.cross_validation[validation]?.pooled.rms ?? null,
    fit_aard: c.fit?.summary.deviations.aard ?? null,
    aic: c.fit?.criteria.aic ?? null,
    bic: c.fit?.criteria.bic ?? null,
  };
}

/** Candidates as `selection.select` expects them. */
export function selectionCandidates(candidates: Candidate[], validation: string) {
  return candidates.map((c) => ({
    name: c.label,
    n_parameters: c.fit?.n_parameters ?? freeParameters(c).length,
    metrics: candidateMetrics(c, validation),
    physics_passed: physicsPassed(c.study) ?? true,
  }));
}

/** Point deviations of a fit grouped by dataset, for plotting ARD against temperature. */
export function deviationSeries(fit: FitResponse): { name: string; x: number[]; y: (number | null)[] }[] {
  const groups = new Map<string, { x: number[]; y: (number | null)[] }>();
  fit.points.dataset.forEach((name, i) => {
    const g = groups.get(name) ?? { x: [], y: [] };
    g.x.push(fit.points.temperature[i]);
    g.y.push(fit.points.ard[i]);
    groups.set(name, g);
  });
  return [...groups].map(([name, g]) => ({ name, ...g }));
}

/** Median relative expanded uncertainty (%) over datasets, for the uncertainty band in deviation plots. */
export function typicalUncertainty(datasets: Dataset[]): number | null {
  const rel: number[] = [];
  for (const d of datasets) {
    d.expanded_uncertainty?.forEach((u, i) => {
      if (d.values[i] !== 0) rel.push((100 * u) / Math.abs(d.values[i]));
    });
  }
  if (rel.length === 0) return null;
  rel.sort((a, b) => a - b);
  const mid = Math.floor(rel.length / 2);
  return rel.length % 2 ? rel[mid] : (rel[mid - 1] + rel[mid]) / 2;
}

/** The dataset without the points whose ids are in ``masked`` (all arrays filtered alike). */
export function applyMask(d: Dataset, masked: number[]): Dataset {
  if (masked.length === 0) return d;
  const drop = new Set(masked);
  const keep = d.point_ids.flatMap((id, i) => (drop.has(id) ? [] : [i]));
  const pick = <T>(a: T[] | null): T[] | null => (a ? keep.map((i) => a[i]) : null);
  return {
    ...d,
    temperature: keep.map((i) => d.temperature[i]),
    values: keep.map((i) => d.values[i]),
    pressure: pick(d.pressure),
    molar_density: pick(d.molar_density),
    expanded_uncertainty: pick(d.expanded_uncertainty),
    phase: pick(d.phase),
    point_ids: keep.map((i) => d.point_ids[i]),
  };
}

/** Per-point deviations (held-out or of a reference model) as plot series per dataset, x = temperature. */
export function pointSeries(
  datasets: Dataset[],
  names: string[],
  pointIds: number[],
  ard: (number | null)[],
): { name: string; x: number[]; y: (number | null)[] }[] {
  const temperatureOf = new Map(datasets.map((d) => [d.name, new Map(d.point_ids.map((id, i) => [id, d.temperature[i]]))]));
  const groups = new Map<string, { x: number[]; y: (number | null)[] }>();
  names.forEach((name, i) => {
    const t = temperatureOf.get(name)?.get(pointIds[i]);
    if (t === undefined) return;
    const g = groups.get(name) ?? { x: [], y: [] };
    g.x.push(t);
    g.y.push(ard[i]);
    groups.set(name, g);
  });
  return [...groups].map(([name, g]) => ({ name, ...g }));
}

export interface MeasuredState {
  temperature: number; // mean, K
  pressure: number | null; // mean, Pa
  phase: string;
  rows: number[]; // indices into the dataset arrays
  mean: number; // mean value, SI
  spread: number; // max - min, SI
}

/** Repeats of one state: points within ``tTol`` K and ``pRel`` relative pressure of a state's first point. */
export function measuredStates(d: Dataset, tTol = 1.0, pRel = 0.02): MeasuredState[] {
  const states: MeasuredState[] = [];
  d.values.forEach((v, i) => {
    const t = d.temperature[i];
    const p = d.pressure?.[i] ?? null;
    const s = states.find((x) => {
      const t0 = d.temperature[x.rows[0]];
      const p0 = d.pressure?.[x.rows[0]] ?? null;
      return Math.abs(t - t0) <= tTol && (p === null || p0 === null || Math.abs(p - p0) <= pRel * p0);
    });
    if (s) s.rows.push(i);
    else states.push({ temperature: t, pressure: p, phase: d.phase?.[i] ?? "", rows: [i], mean: v, spread: 0 });
  });
  for (const s of states) {
    const vals = s.rows.map((i) => d.values[i]);
    s.temperature = s.rows.reduce((a, i) => a + d.temperature[i], 0) / s.rows.length;
    s.pressure = d.pressure ? s.rows.reduce((a, i) => a + (d.pressure?.[i] ?? 0), 0) / s.rows.length : null;
    s.mean = vals.reduce((a, b) => a + b, 0) / vals.length;
    s.spread = Math.max(...vals) - Math.min(...vals);
  }
  return states;
}
