// Scales and ticks for the SVG plots (display only: the data come from the worker).

export interface Scale {
  domain: [number, number];
  range: [number, number];
  map: (v: number) => number;
  ticks: number[];
}

/** "Nice" tick values (1, 2, 5 × 10ⁿ steps) covering [min, max]. */
export function niceTicks(min: number, max: number, count = 6): number[] {
  if (!Number.isFinite(min) || !Number.isFinite(max)) return [];
  if (min === max) {
    const pad = min === 0 ? 1 : Math.abs(min) * 0.1;
    return niceTicks(min - pad, max + pad, count);
  }
  if (min > max) [min, max] = [max, min];
  const raw = (max - min) / Math.max(1, count - 1);
  const power = 10 ** Math.floor(Math.log10(raw));
  const step = [1, 2, 2.5, 5, 10].map((m) => m * power).find((s) => s >= raw) ?? 10 * power;
  const start = Math.floor(min / step) * step;
  const ticks: number[] = [];
  for (let v = start; v <= max + step * 1e-9; v += step) {
    ticks.push(Number(v.toPrecision(12)));
  }
  if (ticks[ticks.length - 1] < max) ticks.push(Number((ticks[ticks.length - 1] + step).toPrecision(12)));
  return ticks;
}

/** Linear scale over the tick-rounded extent of `values` (nulls and non-finite values ignored). */
export function linearScale(values: (number | null)[], range: [number, number], count = 6, include?: number): Scale {
  const finite = values.filter((v): v is number => v !== null && Number.isFinite(v));
  if (include !== undefined) finite.push(include);
  const lo = finite.length ? Math.min(...finite) : 0;
  const hi = finite.length ? Math.max(...finite) : 1;
  const ticks = niceTicks(lo, hi, count);
  const domain: [number, number] = ticks.length ? [ticks[0], ticks[ticks.length - 1]] : [lo, hi];
  const span = domain[1] - domain[0] || 1;
  const map = (v: number) => range[0] + ((v - domain[0]) / span) * (range[1] - range[0]);
  return { domain, range, map, ticks };
}

/** Short tick label: no trailing zeros, exponent notation for very large or small magnitudes. */
export function tickLabel(v: number): string {
  if (v === 0) return "0";
  const a = Math.abs(v);
  if (a >= 1e5 || a < 1e-3) return v.toExponential(1).replace("e+", "e");
  return String(Number(v.toPrecision(6)));
}

export const SERIES_COLORS = ["#1f5fa8", "#b5540a", "#2e7d32", "#6a1b9a", "#c62828", "#00838f", "#5d4037"];
export const SERIES_SHAPES = ["square", "triangle", "circle", "diamond"] as const;
export type Shape = (typeof SERIES_SHAPES)[number];

export interface Series {
  name: string;
  x: number[];
  y: (number | null)[];
  color?: string;
  shape?: Shape;
  open?: boolean;
  /** Symmetric error bar half-widths (same units as y), e.g. expanded uncertainties. */
  err?: (number | null)[];
}

export interface Line {
  name: string;
  x: number[];
  y: (number | null)[];
  color?: string;
  dashed?: boolean;
}
