// Standard figure specs (propbench.figures) built from the project, for reports and the figure set.
import type { Dataset } from "./types";

interface Unit {
  symbol: string;
  unit: string;
  factor: number;
}

export interface FigureSpec {
  preset: string;
  x: { label: string };
  y: { label: string };
  layers: object[];
  legend?: boolean;
}

const MARKERS = ["square", "triangle", "circle", "diamond", "down", "plus", "cross"];

export function stateMap(datasets: Dataset[], preset = "elsevier1"): FigureSpec {
  return {
    preset,
    x: { label: "Temperature, T / K" },
    y: { label: "Pressure, p / MPa" },
    layers: datasets
      .filter((d) => d.pressure)
      .map((d, i) => ({ type: "points", name: d.name, x: d.temperature, y: (d.pressure ?? []).map((p) => p * 1e-6), marker: MARKERS[i % MARKERS.length] })),
  };
}

export function propertyPlot(datasets: Dataset[], unit: Unit, preset = "elsevier1"): FigureSpec {
  return {
    preset,
    x: { label: "Temperature, T / K" },
    y: { label: `${unit.symbol} / ${unit.unit}` },
    layers: datasets.map((d, i) => ({
      type: "points",
      name: d.name,
      x: d.temperature,
      y: d.values.map((v) => v * unit.factor),
      err: d.expanded_uncertainty?.map((u) => u * unit.factor),
      marker: MARKERS[i % MARKERS.length],
    })),
  };
}

/** Relative deviations (%) of one model per dataset, against temperature. */
export function deviationPlot(
  points: { dataset: string[]; temperature: number[]; ard: (number | null)[] },
  model: string,
  unit: Unit,
  preset = "elsevier1",
): FigureSpec {
  const names = [...new Set(points.dataset)];
  return {
    preset,
    x: { label: "Temperature, T / K" },
    y: { label: `100 (${unit.symbol}exp − ${unit.symbol}model)/${unit.symbol}model (${model})` },
    layers: [
      { type: "hline", y: 0 },
      ...names.map((n, i) => {
        const idx = points.dataset.map((d, j) => (d === n ? j : -1)).filter((j) => j >= 0);
        return { type: "points", name: n, x: idx.map((j) => points.temperature[j]), y: idx.map((j) => points.ard[j]), marker: MARKERS[i % MARKERS.length] };
      }),
    ],
  };
}
