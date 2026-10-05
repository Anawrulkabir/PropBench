// Import mapping helpers: guess what each column holds from its header, and build the mapping the worker reads.
// The guess is only a starting point the user confirms in the import dialog; units are converted by the worker.

import type { ColumnSpec, ImportMapping } from "./types";

export const ROLES = ["ignore", "temperature", "pressure", "molar_density", "value", "uncertainty", "phase"] as const;
export type RoleChoice = (typeof ROLES)[number];

export const ROLE_LABELS: Record<RoleChoice, string> = {
  ignore: "(ignore)",
  temperature: "Temperature",
  pressure: "Pressure",
  molar_density: "Molar density",
  value: "Property value",
  uncertainty: "Uncertainty",
  phase: "Phase",
};

/** Units offered per role (pint spellings understood by the worker). */
export const UNITS: Record<string, string[]> = {
  temperature: ["K", "degC"],
  pressure: ["MPa", "kPa", "Pa", "bar"],
  molar_density: ["mol/m^3", "mol/L", "mol/dm^3"],
  viscosity: ["uPa*s", "mPa*s", "Pa*s", "cP"],
  thermal_conductivity: ["mW/(m*K)", "W/(m*K)"],
  speed_of_sound: ["m/s"],
  surface_tension: ["mN/m", "N/m"],
  vapor_pressure: ["MPa", "kPa", "Pa", "bar"],
};

export const UNCERTAINTY_KINDS = [
  { kind: "relative_percent", label: "% of value" },
  { kind: "relative_fraction", label: "fraction of value" },
  { kind: "absolute", label: "absolute" },
] as const;

export interface ColumnChoice {
  role: RoleChoice;
  unit: string;
  uncertaintyKind: string;
}

const has = (text: string, re: RegExp) => re.test(text);

/** Guess role and unit of one column from its header, e.g. "p [MPa]", "T/°C", "η (µPa·s)", "U(%)". */
export function guessColumn(header: string, quantity: string): ColumnChoice {
  const h = header.trim();
  const lower = h.toLowerCase();
  const unitIn = (options: string[], fallback: string) => {
    const bracket = /[[(/]\s*([^\])]+?)\s*[\])]?$/.exec(h)?.[1]?.toLowerCase().replace(/[µμ]/g, "u") ?? "";
    const compact = bracket.replace(/[\s·.*]/g, "");
    return options.find((u) => compact === u.toLowerCase().replace(/[\s·.*^]/g, "")) ?? fallback;
  };
  if (has(lower, /^(t|temp|temperature)\b|^t\s*[[(/]|temperatur/)) {
    return { role: "temperature", unit: has(lower, /°c|degc|celsius|\bc\]/) ? "degC" : "K", uncertaintyKind: "" };
  }
  if (has(lower, /^(p|press|pressure)\b|^p\s*[[(/]|druck/)) {
    const unit = has(lower, /kpa/) ? "kPa" : has(lower, /\bbar\b/) ? "bar" : has(lower, /mpa/) ? "MPa" : "Pa";
    return { role: "pressure", unit, uncertaintyKind: "" };
  }
  if (has(lower, /phase|state/)) return { role: "phase", unit: "", uncertaintyKind: "" };
  if (has(lower, /^(u|unc|uncert|uncertainty)\b|^u\s*[[(/(]|uncert|^δ|^±/)) {
    const kind = has(lower, /%|percent/) ? "relative_percent" : "absolute";
    return { role: "uncertainty", unit: "", uncertaintyKind: kind };
  }
  if (has(lower, /^(rho|ρ|dens|density|d)\b|^ρ/) && has(lower, /mol/)) {
    return { role: "molar_density", unit: has(lower, /mol\/l|dm/) ? "mol/L" : "mol/m^3", uncertaintyKind: "" };
  }
  const valueWords: Record<string, RegExp> = {
    viscosity: /^(eta|η|visc|mu\b)|viscosity/,
    thermal_conductivity: /^(lambda|λ|k\b)|conductivity/,
    speed_of_sound: /^(w|c|u)\b.*m\/s|speed|sound/,
    surface_tension: /^(sigma|σ)|tension/,
    vapor_pressure: /^(psat|p_sat|ps)\b|vapou?r/,
  };
  if (valueWords[quantity] && has(lower, valueWords[quantity])) {
    const units = UNITS[quantity] ?? [];
    return { role: "value", unit: unitIn(units, units[0] ?? ""), uncertaintyKind: "" };
  }
  return { role: "ignore", unit: "", uncertaintyKind: "" };
}

/** The mapping for the worker; throws with a readable message when a required column is missing. */
export function buildMapping(
  headers: string[],
  choices: ColumnChoice[],
  quantity: string,
  headerRow: number,
  coverageFactor: number,
  sheet: string | null,
  firstDataRow: number | null = null,
): ImportMapping {
  const columns: ColumnSpec[] = [];
  const seen = new Set<string>();
  choices.forEach((c, i) => {
    if (c.role === "ignore") return;
    if (seen.has(c.role)) throw new Error(`Two columns are mapped as ${ROLE_LABELS[c.role]}.`);
    seen.add(c.role);
    const spec: ColumnSpec = { column: headers[i] ?? "", role: c.role };
    if (c.unit) spec.unit = c.unit;
    if (c.role === "uncertainty") spec.uncertainty_kind = c.uncertaintyKind || "relative_percent";
    columns.push(spec);
  });
  if (!seen.has("temperature")) throw new Error("Map a temperature column.");
  if (!seen.has("value")) throw new Error("Map the column with the property values.");
  if (!seen.has("pressure") && !seen.has("molar_density") && quantity !== "vapor_pressure") {
    throw new Error("Map a pressure or molar-density column to define the state of each point.");
  }
  const mapping: ImportMapping = {
    kind: "propbench.import-mapping",
    version: 1,
    quantity,
    columns,
    coverage_factor: coverageFactor,
    header_row: headerRow,
  };
  if (firstDataRow !== null) mapping.first_data_row = firstDataRow;
  if (sheet !== null) mapping.sheet = sheet;
  return mapping;
}
