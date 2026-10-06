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

/** The worker operations of protocol v2 (whitelisted by `pb_engine::Method`). */
export type WorkerMethod =
  | "fluids"
  | "properties"
  | "dataset.preview"
  | "dataset.import"
  | "dataset.check"
  | "model.kinds"
  | "model.default"
  | "model.predict"
  | "model.fit"
  | "study.validate"
  | "selection.lock"
  | "selection.select"
  | "consistency.analyze"
  | "model.references"
  | "model.compare"
  | "components.list"
  | "components.install"
  | "components.install_file"
  | "components.remove"
  | "components.datasets";

/** Run one worker operation through the `worker` Tauri command → pb-engine → Python worker. */
export function worker<T>(method: WorkerMethod, params: object = {}): Promise<T> {
  return invoke<T>("worker", { method, params });
}

/** Stop the running worker operation; pending calls fail with kind "cancelled". */
export function cancelWorker(): Promise<void> {
  return invoke<void>("cancel");
}

/** True inside the desktop app (Tauri), false in a plain browser (e.g. UI tests). */
export function inTauri(): boolean {
  return typeof window !== "undefined" && "__TAURI_INTERNALS__" in window;
}

/** Base64 of a file's bytes, to send a picked file to the worker without a filesystem path. */
export async function fileToBase64(file: Blob): Promise<string> {
  const bytes = new Uint8Array(await file.arrayBuffer());
  let binary = "";
  const chunk = 0x8000;
  for (let i = 0; i < bytes.length; i += chunk) {
    binary += String.fromCharCode(...bytes.subarray(i, i + chunk));
  }
  return btoa(binary);
}
