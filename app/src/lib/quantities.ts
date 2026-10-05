// Display units for quantities (conversion at the display boundary only; the worker is SI).

export interface DisplayUnit {
  label: string;
  symbol: string;
  unit: string;
  factor: number; // display value = SI value × factor
}

export const DISPLAY: Record<string, DisplayUnit> = {
  temperature: { label: "Temperature", symbol: "T", unit: "K", factor: 1 },
  pressure: { label: "Pressure", symbol: "p", unit: "MPa", factor: 1e-6 },
  molar_density: { label: "Molar density", symbol: "ρ", unit: "mol/m³", factor: 1 },
  viscosity: { label: "Viscosity", symbol: "η", unit: "µPa·s", factor: 1e6 },
  thermal_conductivity: { label: "Thermal conductivity", symbol: "λ", unit: "mW/(m·K)", factor: 1e3 },
  speed_of_sound: { label: "Speed of sound", symbol: "w", unit: "m/s", factor: 1 },
  surface_tension: { label: "Surface tension", symbol: "σ", unit: "mN/m", factor: 1e3 },
  vapor_pressure: { label: "Vapour pressure", symbol: "pₛ", unit: "MPa", factor: 1e-6 },
  mass_density: { label: "Density", symbol: "ρ", unit: "kg/m³", factor: 1 },
};

export const QUANTITIES = [
  "viscosity",
  "thermal_conductivity",
  "speed_of_sound",
  "surface_tension",
  "vapor_pressure",
] as const;

export function display(quantity: string): DisplayUnit {
  return DISPLAY[quantity] ?? { label: quantity, symbol: quantity, unit: "SI", factor: 1 };
}

/** A number with `digits` significant digits, or an en dash for missing values. */
export function fmt(value: number | null | undefined, digits = 4): string {
  if (value === null || value === undefined || !Number.isFinite(value)) return "–";
  if (value === 0) return "0";
  const a = Math.abs(value);
  if (a >= 1e6 || a < 1e-4) return value.toExponential(digits - 1);
  return String(Number(value.toPrecision(digits)));
}

/** A percentage with fixed decimals. */
export function pct(value: number | null | undefined, decimals = 2): string {
  if (value === null || value === undefined || !Number.isFinite(value)) return "–";
  return value.toFixed(decimals);
}

/** A parameter value with its standard error, both to the precision the error supports. */
export function withError(value: number, error: number | null | undefined): string {
  if (error === null || error === undefined || !Number.isFinite(error) || error <= 0) return fmt(value, 6);
  const decimals = Math.max(0, Math.min(10, 1 - Math.floor(Math.log10(error))));
  return `${value.toFixed(decimals)} ± ${error.toFixed(decimals)}`;
}
