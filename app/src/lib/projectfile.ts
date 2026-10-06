// The project file content (mirrors `pb_store::Project`): what Save writes and Open reads. Pure functions, so the
// mapping between the in-memory project and the file is tested without Tauri.

import type { Candidate } from "./study";
import type { CheckEntry, CompareResponse, ConsistencyResponse, Dataset, SelectionResponse, SelectionRule } from "./types";

export interface ProjectMeta {
  name: string;
  created: number;
  modified: number;
  app_version: string;
  schema_version?: number;
}

export interface DatasetRecord {
  name: string;
  data: Dataset;
}

export interface Snapshot {
  id: number;
  label: string;
  created: number;
  datasets: DatasetRecord[];
  documents: Record<string, unknown>;
}

export interface AuditEntry {
  time: number;
  action: string;
  detail: string;
}

export interface ProjectContent {
  meta: ProjectMeta;
  datasets: DatasetRecord[];
  documents: Record<string, unknown>;
  snapshots: Snapshot[];
  audit: AuditEntry[];
}

/** The parts of the open project that are saved (everything except transient UI state such as the log). */
export interface SavedState {
  name: string;
  datasets: Dataset[];
  checks: Record<string, CheckEntry>;
  candidates: Candidate[];
  settings: unknown;
  rule: SelectionRule;
  locked: { sha256: string; at: string; rule: SelectionRule } | null;
  selection: SelectionResponse | null;
  masks: Record<string, number[]>;
  consistency: ConsistencyResponse | null;
  comparison: CompareResponse | null;
  consistencySettings: unknown;
  /** Python scripts of the project (file name → text), run in the project environment. */
  scripts: Record<string, string>;
  /** Project environment: packages asked for and the lock of exactly installed versions. */
  environment: { packages: string[]; lock: string };
}

/** Document keys in the file; documents not listed here (written by newer versions) are kept as they are. */
export const DOCUMENT_KEYS = [
  "checks",
  "candidates",
  "settings",
  "rule",
  "locked",
  "selection",
  "masks",
  "consistency",
  "comparison",
  "consistencySettings",
  "scripts",
  "environment",
] as const;

export function nowSeconds(): number {
  return Math.floor(Date.now() / 1000);
}

function plain<T>(value: T): T {
  return value === undefined ? value : (JSON.parse(JSON.stringify(value)) as T);
}

export function documentsOf(state: SavedState): Record<string, unknown> {
  const out: Record<string, unknown> = {};
  for (const key of DOCUMENT_KEYS) out[key] = plain(state[key]);
  return out;
}

/** Build the file content from the open project. `previous` keeps creation time, snapshots, audit and unknown docs. */
export function toContent(state: SavedState, previous: ProjectContent | null, audit: AuditEntry[]): ProjectContent {
  const meta: ProjectMeta = previous
    ? { ...previous.meta, name: state.name }
    : { name: state.name, created: nowSeconds(), modified: nowSeconds(), app_version: "" };
  return {
    meta,
    datasets: state.datasets.map((d) => ({ name: d.name, data: plain(d) })),
    documents: { ...(previous?.documents ?? {}), ...documentsOf(state) },
    snapshots: previous?.snapshots ?? [],
    audit: [...(previous?.audit ?? []), ...audit],
  };
}

/** The open-project state stored in a file; missing documents take the given defaults. */
export function fromContent(content: ProjectContent, defaults: SavedState): SavedState {
  const doc = <K extends keyof SavedState>(key: K): SavedState[K] =>
    (key in content.documents ? content.documents[key] : defaults[key]) as SavedState[K];
  return {
    name: content.meta.name || defaults.name,
    datasets: content.datasets.map((r) => ({ ...r.data, name: r.name })),
    checks: doc("checks"),
    candidates: doc("candidates"),
    settings: doc("settings"),
    rule: doc("rule"),
    locked: doc("locked"),
    selection: doc("selection"),
    masks: doc("masks"),
    consistency: doc("consistency"),
    comparison: doc("comparison"),
    consistencySettings: doc("consistencySettings"),
    scripts: doc("scripts"),
    environment: doc("environment"),
  };
}

/** A new snapshot of the current datasets and documents (ids increase; snapshots are never renumbered). */
export function addSnapshot(content: ProjectContent, label: string): ProjectContent {
  const id = Math.max(0, ...content.snapshots.map((s) => s.id)) + 1;
  const snapshot: Snapshot = {
    id,
    label,
    created: nowSeconds(),
    datasets: plain(content.datasets),
    documents: plain(content.documents),
  };
  return {
    ...content,
    snapshots: [...content.snapshots, snapshot],
    audit: [...content.audit, { time: nowSeconds(), action: "snapshot", detail: `${id}: ${label}` }],
  };
}

/** The content with datasets and documents of snapshot `id` (snapshots and audit kept). */
export function restoreSnapshot(content: ProjectContent, id: number): ProjectContent {
  const snap = content.snapshots.find((s) => s.id === id);
  if (!snap) throw new Error(`no snapshot ${id}`);
  return {
    ...content,
    datasets: plain(snap.datasets),
    documents: plain(snap.documents),
    audit: [...content.audit, { time: nowSeconds(), action: "restore", detail: `${id}: ${snap.label}` }],
  };
}

/** Text that changes whenever anything saved changes: the project is dirty when it differs from the saved one. */
export function fingerprint(state: SavedState): string {
  return JSON.stringify([state.name, state.datasets, documentsOf(state)]);
}
