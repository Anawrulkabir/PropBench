import { invoke } from "@tauri-apps/api/core";
import { mpaToPa } from "./units";

/** Mirrors `pb_engine::PropertyRequest`: SI units, CoolProp input pair and output names. */
export interface PropertyRequest {
  fluid: string;
  pair: string;
  values: [number, number];
  output: string;
}

/** Mirrors `pb_engine::PropertyResult`. */
export interface PropertyResult {
  value: number;
  output: string;
  backend: string;
  backend_version: string;
}

/** Error returned by the `property` Tauri command. */
export interface CommandError {
  kind: string;
  message: string;
}

export type FormResult = { ok: true; request: PropertyRequest } | { ok: false; error: string };

/** Validate the calculator inputs (T in K, p in MPa) and build an SI density request. */
export function densityRequest(fluid: string, temperatureK: string, pressureMPa: string): FormResult {
  const name = fluid.trim();
  if (name === "") return { ok: false, error: "Enter a fluid name, e.g. R134a." };
  const t = parseNumber(temperatureK);
  if (t === null || t <= 0) return { ok: false, error: "Temperature must be a positive number in K." };
  const p = parseNumber(pressureMPa);
  if (p === null || p <= 0) return { ok: false, error: "Pressure must be a positive number in MPa." };
  return { ok: true, request: { fluid: name, pair: "PT_INPUTS", values: [mpaToPa(p), t], output: "Dmass" } };
}

function parseNumber(text: string): number | null {
  const trimmed = text.trim();
  if (trimmed === "") return null;
  const value = Number(trimmed);
  return Number.isFinite(value) ? value : null;
}

export function errorMessage(err: unknown): string {
  if (typeof err === "object" && err !== null && "message" in err) return String((err as CommandError).message);
  return String(err);
}

/** Ask the engine (and through it the Python worker) for one property. The UI never computes. */
export function computeProperty(request: PropertyRequest): Promise<PropertyResult> {
  return invoke<PropertyResult>("property", { request });
}
