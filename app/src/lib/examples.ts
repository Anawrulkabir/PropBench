// Example projects built from published data (see examples/SOURCE.md). Only the datasets are assembled here; the
// saturation states of saturated data are computed by the worker.

import cf3i from "./examples/cf3i_viscosity.json";
import type { Dataset } from "./types";

interface RawPoint {
  T: number;
  p?: number;
  eta: number;
}
interface RawDataset {
  id: string;
  source: string;
  doi: string;
  phase: string;
  method: string;
  U_rel?: number;
  U_rel_max?: number;
  points: RawPoint[];
}

export interface ExampleDataset {
  dataset: Omit<Dataset, "pressure" | "molar_density"> & { pressure: number[] | null; molar_density: number[] | null };
  /** "liquid" when the pressures must come from the saturation curve of the reference EoS. */
  saturation: "liquid" | null;
}

/** The CF3I viscosity datasets in SI (Pa, Pa·s), expanded uncertainties with k = 2. */
export function cf3iExample(): ExampleDataset[] {
  return (cf3i.datasets as RawDataset[]).map((d) => {
    const t = d.points.map((p) => p.T);
    const eta = d.points.map((p) => p.eta * 1e-6);
    const u = d.U_rel ?? d.U_rel_max ?? 0;
    const saturated = d.points.every((p) => p.p === undefined);
    return {
      dataset: {
        schema_version: 1,
        name: d.id,
        fluid: "R13I1",
        quantity: "viscosity",
        temperature: t,
        values: eta,
        pressure: saturated ? null : d.points.map((p) => (p.p ?? 0) * 1e6),
        molar_density: null,
        expanded_uncertainty: eta.map((v) => (v * u) / 100),
        coverage_factor: 2,
        phase: saturated ? t.map(() => "liquid") : null,
        point_ids: t.map((_, i) => i),
        provenance: { doi: d.doi, citation: d.source, method: d.method, purity: null, notes: null },
      },
      saturation: saturated ? "liquid" : null,
    };
  });
}
