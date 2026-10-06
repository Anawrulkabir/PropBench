// The open project: datasets, candidate models, studies and the output log. All computation goes through the
// worker (`worker()` → Tauri → pb-engine → Python); this module only keeps state and sequences the calls.

import { invoke } from "@tauri-apps/api/core";
import { ask, open as openDialog, save as saveDialog } from "@tauri-apps/plugin-dialog";
import { cancelWorker, errorMessage, fileToBase64, inTauri, worker } from "./api";
import {
  addSnapshot,
  type AuditEntry,
  fingerprint,
  fromContent,
  nowSeconds,
  type ProjectContent,
  restoreSnapshot,
  type SavedState,
  type Snapshot,
  toContent,
} from "./projectfile";
import { applyMask, type Candidate, commonTarget, selectionCandidates, uniqueName } from "./study";
import type {
  CheckEntry,
  CompareResponse,
  ConsistencyResponse,
  Dataset,
  FitResponse,
  ImportMapping,
  ModelKind,
  ModelSpec,
  Preview,
  SelectionResponse,
  SelectionRule,
  StudyResponse,
} from "./types";

export type View =
  | "data"
  | "consistency"
  | "deviations"
  | "fit"
  | "fitting"
  | "study"
  | "results"
  | "worksheet"
  | "graph"
  | "calculator"
  | "code"
  | "surface"
  | "experiment"
  | "setup"
  | "cad";

export type Dialog = "import" | "wizard" | "settings" | "components" | "addons" | "about" | null;

export interface LogLine {
  time: string;
  text: string;
  level: "info" | "warn" | "error";
}

export interface StudySettings {
  methods: string[];
  k: number;
  nBootstrap: number;
  seed: number;
  workers: number;
  weighted: boolean;
  scaleFactors: boolean;
  multistart: number;
}

export type Selected = { type: "dataset"; name: string } | { type: "candidate"; id: string } | null;

function now(): string {
  return new Date().toTimeString().slice(0, 8);
}

class Project {
  name = $state("Untitled project");
  datasets = $state<Dataset[]>([]);
  checks = $state<Record<string, CheckEntry>>({});
  candidates = $state<Candidate[]>([]);
  kinds = $state<ModelKind[]>([]);
  settings = $state<StudySettings>({
    methods: ["lostate"],
    k: 5,
    nBootstrap: 50,
    seed: 0,
    workers: 1,
    weighted: true,
    scaleFactors: false,
    multistart: 0,
  });
  rule = $state<SelectionRule>({
    metric: "cv_aard",
    validation: "lostate",
    tie_tolerance: 0.05,
    require_physics: true,
    notes: "",
  });
  locked = $state<{ sha256: string; at: string; rule: SelectionRule } | null>(null);
  selection = $state<SelectionResponse | null>(null);
  log = $state<LogLine[]>([]);
  status = $state("Ready");
  busy = $state<string | null>(null);
  view = $state<View>("data");
  selected = $state<Selected>(null);
  importOpen = $state(false);
  dialog = $state<Dialog>(null);
  /** Point ids excluded from fits, validation and consistency (kept and shown in the worksheet). */
  masks = $state<Record<string, number[]>>({});
  /** Dataset shown in the worksheet tab. */
  worksheet = $state<string | null>(null);
  stopRequested = $state(false);
  /** Document tabs of the work area, in order (fixed ones first, then tabs opened from the menus). */
  tabs = $state<View[]>(["data", "consistency", "deviations", "fit", "fitting", "study", "results"]);

  /** Path of the open project file, or null for a project not saved yet. */
  filePath = $state<string | null>(null);
  /** Snapshots stored in the project file (newest last). */
  snapshots = $state<Snapshot[]>([]);
  /** Fingerprint of the state last saved or opened; the project is dirty when the current one differs. */
  savedFingerprint = $state("");
  /** Content last saved or opened (keeps creation time, audit and documents of newer versions). */
  private fileContent: ProjectContent | null = null;
  /** Audit entries since the last save. */
  private pendingAudit: AuditEntry[] = [];

  /** Earlier states for Edit › Undo (masking, removing, importing), newest last. */
  undoStack = $state<{ label: string; state: string }[]>([]);

  /** Remember the current state before a change that Undo can revert. */
  checkpoint(label: string) {
    this.undoStack.push({ label, state: JSON.stringify(this.savedState()) });
    if (this.undoStack.length > 30) this.undoStack.shift();
  }

  undo() {
    const last = this.undoStack.pop();
    if (!last) return;
    this.apply(JSON.parse(last.state) as SavedState);
    this.note(`Undid: ${last.label}`);
  }

  constructor() {
    this.savedFingerprint = fingerprint(this.savedState());
  }

  open(view: View) {
    if (!this.tabs.includes(view)) this.tabs.push(view);
    this.view = view;
  }

  closeTab(view: View) {
    this.tabs = this.tabs.filter((v) => v !== view);
    if (this.view === view) this.view = this.tabs[this.tabs.length - 1] ?? "data";
  }
  consistency = $state<ConsistencyResponse | null>(null);
  comparison = $state<CompareResponse | null>(null);
  consistencySettings = $state({ tTol: 1.0, references: true });

  note(text: string, level: LogLine["level"] = "info") {
    this.log.push({ time: now(), text, level });
    this.status = text;
  }

  /** Run one step with the busy indicator; errors go to the log and are returned as a message. */
  async run<T>(label: string, step: () => Promise<T>): Promise<T | null> {
    this.busy = label;
    this.status = `${label}…`;
    try {
      return await step();
    } catch (err) {
      const kind = typeof err === "object" && err !== null && "kind" in err ? (err as { kind: string }).kind : "";
      if (kind === "cancelled") this.note(`${label} stopped`, "warn");
      else this.note(`${label} failed: ${errorMessage(err)}`, "error");
      return null;
    } finally {
      this.busy = null;
    }
  }

  /** Datasets without their masked points: what fits, validation and consistency use. */
  activeDatasets(): Dataset[] {
    return this.datasets.map((d) => applyMask(d, this.masks[d.name] ?? [])).filter((d) => d.values.length > 0);
  }

  setMask(name: string, ids: number[], masked: boolean) {
    this.checkpoint(`${masked ? "mask" : "unmask"} ${ids.length} point${ids.length === 1 ? "" : "s"} of ${name}`);
    const current = new Set(this.masks[name] ?? []);
    for (const id of ids) {
      if (masked) current.add(id);
      else current.delete(id);
    }
    this.masks[name] = [...current].sort((a, b) => a - b);
    this.invalidateResults();
    this.audit(masked ? "mask" : "unmask", `${name}: ${ids.join(", ")}`);
    this.note(`${name}: ${ids.length} point${ids.length === 1 ? "" : "s"} ${masked ? "masked" : "unmasked"} (${current.size} masked)`);
  }

  openWorksheet(name: string) {
    this.worksheet = name;
    this.selected = { type: "dataset", name };
    this.open("worksheet");
  }

  /** Stop: the running worker operation is cancelled and a running sequence (fit all, study) stops. */
  stop() {
    if (!this.busy) return;
    this.stopRequested = true;
    this.note("Stopping: the running operation is cancelled", "warn");
    if (inTauri()) cancelWorker().catch(() => undefined);
  }

  // --- project file (.pbp) ---

  audit(action: string, detail: string) {
    this.pendingAudit.push({ time: nowSeconds(), action, detail });
  }

  savedState(): SavedState {
    return {
      name: this.name,
      datasets: this.datasets,
      checks: this.checks,
      candidates: this.candidates,
      settings: this.settings,
      rule: this.rule,
      locked: this.locked,
      selection: this.selection,
      masks: this.masks,
      consistency: this.consistency,
      comparison: this.comparison,
      consistencySettings: this.consistencySettings,
    };
  }

  private defaults(): SavedState {
    return {
      name: "Untitled project",
      datasets: [],
      checks: {},
      candidates: [],
      settings: { methods: ["lostate"], k: 5, nBootstrap: 50, seed: 0, workers: 1, weighted: true, scaleFactors: false, multistart: 0 },
      rule: { metric: "cv_aard", validation: "lostate", tie_tolerance: 0.05, require_physics: true, notes: "" },
      locked: null,
      selection: null,
      masks: {},
      consistency: null,
      comparison: null,
      consistencySettings: { tTol: 1.0, references: true },
    };
  }

  private apply(state: SavedState) {
    this.name = state.name;
    this.datasets = state.datasets;
    this.checks = state.checks;
    this.candidates = state.candidates;
    this.settings = state.settings as StudySettings;
    this.rule = state.rule;
    this.locked = state.locked;
    this.selection = state.selection;
    this.masks = state.masks;
    this.consistency = state.consistency;
    this.comparison = state.comparison;
    this.consistencySettings = state.consistencySettings as { tTol: number; references: boolean };
    this.selected = null;
    this.worksheet = null;
  }

  isDirty(): boolean {
    return fingerprint(this.savedState()) !== this.savedFingerprint;
  }

  private loaded(content: ProjectContent, path: string | null) {
    this.undoStack = [];
    this.apply(fromContent(content, this.defaults()));
    this.fileContent = content;
    this.snapshots = content.snapshots;
    this.filePath = path;
    this.pendingAudit = [];
    this.savedFingerprint = fingerprint(this.savedState());
  }

  /** Ask before discarding unsaved changes; true when it is fine to go on. */
  private async confirmDiscard(): Promise<boolean> {
    if (!this.isDirty()) return true;
    const text = `${this.name} has unsaved changes. Discard them?`;
    return inTauri() ? ask(text, { title: "PropBench", kind: "warning" }) : window.confirm(text);
  }

  async newProject() {
    if (!(await this.confirmDiscard())) return;
    this.loaded(toContent(this.defaults(), null, []), null);
    this.consistency = null;
    this.log = [];
    this.note("New project");
    this.discardAutosave();
  }

  async openProject(path?: string) {
    if (!(await this.confirmDiscard())) return;
    const chosen =
      path ?? (await openDialog({ multiple: false, directory: false, filters: [{ name: "PropBench project", extensions: ["pbp"] }] }));
    if (typeof chosen !== "string") return;
    const content = await this.run("Open project", () => invoke<ProjectContent>("project_open", { path: chosen }));
    if (!content) return;
    this.loaded(content, chosen);
    this.note(`Opened ${chosen}: ${content.datasets.length} datasets, ${content.snapshots.length} snapshots`);
  }

  /** Save to the current file, or ask for one (always with `saveAs`). Returns true when saved. */
  async saveProject(saveAs = false): Promise<boolean> {
    let path = saveAs ? null : this.filePath;
    if (!path) {
      const chosen = await saveDialog({
        defaultPath: `${this.name.replace(/[\\/:*?"<>|]+/g, "_")}.pbp`,
        filters: [{ name: "PropBench project", extensions: ["pbp"] }],
      });
      if (!chosen) return false;
      path = chosen.endsWith(".pbp") ? chosen : `${chosen}.pbp`;
    }
    const target = path;
    const content = toContent(this.savedState(), this.fileContent, this.pendingAudit);
    const saved = await this.run("Save project", () => invoke<ProjectContent>("project_save", { path: target, project: content }));
    if (!saved) return false;
    this.loaded(saved, target);
    this.note(`Saved ${target}`);
    return true;
  }

  /** Recovery copy in the app data folder when there are unsaved changes (called on a timer). */
  async autosave() {
    if (!inTauri() || this.busy || !this.isDirty()) return;
    const content = toContent(this.savedState(), this.fileContent, this.pendingAudit);
    try {
      await invoke("project_autosave", { project: content });
    } catch (err) {
      this.note(`Autosave failed: ${errorMessage(err)}`, "warn");
    }
  }

  discardAutosave() {
    if (inTauri()) invoke("project_discard_autosave").catch(() => undefined);
  }

  /** At start-up: offer the recovery copy of a session that ended without saving. */
  async recover() {
    if (!inTauri()) return;
    try {
      const content = await invoke<ProjectContent | null>("project_recover");
      if (!content) return;
      const when = new Date(content.meta.modified * 1000).toLocaleString();
      const yes = await ask(`Restore the unsaved project "${content.meta.name}" from ${when}?`, {
        title: "PropBench: recover project",
        kind: "info",
      });
      if (yes) {
        this.loaded(content, null);
        this.savedFingerprint = "";
        this.note(`Recovered unsaved project ${content.meta.name} (save it to keep it)`, "warn");
      } else {
        this.discardAutosave();
      }
    } catch (err) {
      this.note(`Recovery copy could not be read: ${errorMessage(err)}`, "warn");
    }
  }

  /** Store the current datasets and settings as a named snapshot (kept in the file at the next save). */
  snapshot(label: string) {
    const base = toContent(this.savedState(), this.fileContent, this.pendingAudit);
    this.pendingAudit = [];
    const content = addSnapshot(base, label);
    this.fileContent = content;
    this.snapshots = content.snapshots;
    this.note(`Snapshot ${content.snapshots[content.snapshots.length - 1].id}: ${label}`);
  }

  async restore(id: number) {
    if (!this.fileContent) return;
    if (!(await this.confirmDiscard())) return;
    const content = restoreSnapshot(this.fileContent, id);
    const fp = this.savedFingerprint;
    this.loaded(content, this.filePath);
    this.savedFingerprint = fp; // restoring is a change: save to keep it
    this.note(`Restored snapshot ${id}`);
  }

  // --- data ---

  async preview(file: File, sheet: string | null, maxRows = 30): Promise<Preview> {
    const content = await fileToBase64(file);
    return worker<Preview>("dataset.preview", {
      content_base64: content,
      filename: file.name,
      sheet,
      max_rows: maxRows,
    });
  }

  async importFile(file: File, mapping: ImportMapping | null, fluid: string | null, name: string | null) {
    return this.run("Import", async () => {
      const content = await fileToBase64(file);
      const result = await worker<{ datasets: Dataset[]; warnings: string[] }>("dataset.import", {
        content_base64: content,
        filename: file.name,
        mapping,
        fluid,
        name,
      });
      this.checkpoint(`import ${file.name}`);
      const names = this.datasets.map((d) => d.name);
      for (const d of result.datasets) {
        d.name = uniqueName(names, d.name);
        names.push(d.name);
        this.datasets.push(d);
        this.note(`Imported ${d.name}: ${d.values.length} points of ${d.quantity} (${d.fluid})`);
        this.audit("import", `${d.name}: ${d.values.length} points from ${file.name}`);
      }
      for (const w of result.warnings) this.note(w, "warn");
      this.selection = null;
      this.consistency = null;
      this.comparison = null;
      await this.checkData();
      return result.datasets.length;
    });
  }

  /** Load the CF3I tutorial data (published values; saturation states of the 1999 data from the reference EoS). */
  async loadExample() {
    await this.run("Load CF3I example", async () => {
      const { cf3iExample } = await import("./examples");
      for (const { dataset, saturation } of cf3iExample()) {
        if (this.datasets.some((d) => d.name === dataset.name)) continue;
        const d = { ...dataset } as Dataset;
        if (saturation) {
          const sat = await worker<{ outputs: Record<string, (number | null)[]> }>("properties", {
            fluid: d.fluid,
            pair: "QT_INPUTS",
            values1: d.temperature.map(() => 0),
            values2: d.temperature,
            outputs: ["P", "Dmolar"],
          });
          d.pressure = sat.outputs.P.map((v) => v ?? 0);
          d.molar_density = sat.outputs.Dmolar.map((v) => v ?? 0);
        }
        this.datasets.push(d);
        this.note(`Loaded ${d.name}: ${d.values.length} points (${d.provenance.citation ?? ""})`);
      }
      this.name = "CF3I viscosity";
      this.selection = null;
      await this.checkData();
    });
  }

  removeDataset(name: string) {
    this.checkpoint(`remove ${name}`);
    this.datasets = this.datasets.filter((d) => d.name !== name);
    delete this.checks[name];
    delete this.masks[name];
    this.invalidateResults();
    this.note(`Removed ${name}`);
  }

  async checkData() {
    if (this.datasets.length === 0) return;
    await this.run("Data check", async () => {
      const result = await worker<{ datasets: CheckEntry[] }>("dataset.check", { datasets: this.datasets });
      for (const entry of result.datasets) {
        this.checks[entry.name] = entry;
        const i = this.datasets.findIndex((d) => d.name === entry.name);
        if (i >= 0 && entry.dataset) this.datasets[i] = entry.dataset;
        const n = Object.keys(entry.errors).length;
        if (entry.phase_mismatches.length) {
          this.note(`${entry.name}: phase stated in the source disagrees with the EoS at ${entry.phase_mismatches.length} points`, "warn");
        }
        if (n) this.note(`${entry.name}: ${n} points outside the equation of state`, "warn");
      }
      this.note(`Data check finished: ${this.datasets.length} datasets`);
    });
  }

  // --- models ---

  async loadKinds() {
    if (this.kinds.length) return;
    const result = await this.run("Model list", () => worker<{ kinds: ModelKind[] }>("model.kinds"));
    if (result) this.kinds = result.kinds;
  }

  async addCandidate(kind: string, referenceFluid: string | null) {
    const target = commonTarget(this.datasets);
    if (typeof target === "string") {
      this.note(target, "warn");
      return;
    }
    await this.run("New model", async () => {
      const { model } = await worker<{ model: ModelSpec }>("model.default", {
        kind,
        fluid: target.fluid,
        reference_fluid: referenceFluid,
      });
      const label = uniqueName(
        this.candidates.map((c) => c.label),
        referenceFluid ? `${model.name} (${referenceFluid})` : model.name,
      );
      const candidate: Candidate = { id: crypto.randomUUID(), label, start: model, fixed: {}, fit: null, study: null, error: null };
      this.candidates.push(candidate);
      this.selected = { type: "candidate", id: candidate.id };
      this.note(`Added model ${label}`);
    });
  }

  candidate(id: string): Candidate | undefined {
    return this.candidates.find((c) => c.id === id);
  }

  removeCandidate(id: string) {
    this.checkpoint(`remove model ${this.candidate(id)?.label ?? ""}`);
    this.candidates = this.candidates.filter((c) => c.id !== id);
    this.selection = null;
  }

  fitOptions(c: Candidate) {
    const s = this.settings;
    return {
      weighted: s.weighted,
      scale_factors: s.scaleFactors,
      multistart: s.multistart,
      seed: s.seed,
      fixed: c.fixed,
    };
  }

  async fit(id: string) {
    const c = this.candidate(id);
    if (!c) return;
    const result = await this.run(`Fit ${c.label}`, () =>
      worker<FitResponse>("model.fit", { model: c.start, datasets: this.activeDatasets(), options: this.fitOptions(c) }),
    );
    const target = this.candidate(id);
    if (!target) return;
    if (result) {
      target.fit = result;
      target.error = null;
      const s = result.summary;
      this.note(
        `Fit ${c.label}: AARD ${s.deviations.aard?.toFixed(3)} %, ${s.nfev} evaluations${s.success ? "" : ` (${s.message})`}`,
        s.success ? "info" : "warn",
      );
    } else {
      target.error = this.status;
    }
  }

  async fitAll() {
    this.stopRequested = false;
    for (const c of [...this.candidates]) {
      if (this.stopRequested) break;
      await this.fit(c.id);
    }
    this.stopRequested = false;
  }

  // --- validation and selection ---

  async validate(id: string) {
    const c = this.candidate(id);
    if (!c) return;
    const s = this.settings;
    const result = await this.run(`Validate ${c.label}`, () =>
      worker<StudyResponse>("study.validate", {
        model: c.start,
        datasets: this.activeDatasets(),
        methods: s.methods,
        options: { weighted: s.weighted, scale_factors: s.scaleFactors, multistart: s.multistart, fixed: c.fixed },
        k: s.k,
        n_bootstrap: s.nBootstrap,
        seed: s.seed,
        workers: s.workers,
        physics: true,
      }),
    );
    const target = this.candidate(id);
    if (!target || !result) return;
    target.study = result;
    for (const [method, cv] of Object.entries(result.cross_validation)) {
      this.note(`${method.toUpperCase()} ${c.label}: ${cv.folds.length} folds, AARD ${cv.pooled.aard?.toFixed(3)} %`);
    }
    const failed = (result.physics ?? []).filter((p) => !p.passed);
    this.note(
      `Physics checks ${c.label}: ${failed.length ? failed.map((p) => p.name).join(", ") + " failed" : "all passed"}`,
      failed.length ? "warn" : "info",
    );
  }

  async lockRule() {
    const result = await this.run("Lock selection rule", () =>
      worker<{ rule: SelectionRule; sha256: string }>("selection.lock", { rule: this.rule }),
    );
    if (result) {
      this.locked = { sha256: result.sha256, at: now(), rule: result.rule };
      this.audit("lock rule", result.sha256);
      this.selection = null;
      this.note(`Selection rule locked (${result.sha256.slice(0, 12)}…) before fitting`);
    }
  }

  unlockRule() {
    this.locked = null;
    this.selection = null;
    for (const c of this.candidates) c.study = null;
    this.note("Selection rule unlocked: validation results cleared (a changed rule starts a new study)", "warn");
  }

  /** Lock the rule if needed, fit and validate every candidate, then select. */
  async runStudy() {
    if (!this.locked) await this.lockRule();
    if (!this.locked) return;
    this.stopRequested = false;
    for (const c of [...this.candidates]) {
      if (this.stopRequested) break;
      await this.fit(c.id);
      if (this.stopRequested) break;
      await this.validate(c.id);
    }
    if (this.stopRequested) {
      this.stopRequested = false;
      this.note("Study stopped by the user", "warn");
      return;
    }
    await this.select();
  }

  async select() {
    if (!this.locked) {
      this.note("Lock the selection rule first.", "warn");
      return;
    }
    const locked = this.locked;
    const result = await this.run("Model selection", () =>
      worker<SelectionResponse>("selection.select", {
        rule: locked.rule,
        sha256: locked.sha256,
        candidates: selectionCandidates(this.candidates, locked.rule.validation),
      }),
    );
    if (result) {
      this.selection = result;
      this.note(`Selected by locked rule: ${result.chosen} (${result.reason})`);
      this.audit("select", `${result.chosen} (rule ${locked.sha256.slice(0, 12)})`);
      this.view = "results";
    }
  }

  /** Fitted candidates as {name, model} for the consistency and comparison operations. */
  fittedModels() {
    return this.candidates.filter((c) => c.fit).map((c) => ({ name: c.label, model: c.fit?.model }));
  }

  async analyzeConsistency() {
    if (this.datasets.length === 0) return;
    const result = await this.run("Consistency", () =>
      worker<ConsistencyResponse>("consistency.analyze", {
        datasets: this.activeDatasets(),
        models: this.fittedModels(),
        include_references: this.consistencySettings.references,
        t_tol: this.consistencySettings.tTol,
      }),
    );
    if (!result) return;
    this.consistency = result;
    for (const o of result.overlaps) {
      this.note(`Consistency: ${o.a} and ${o.b} overlap at ${o.t_range[0].toFixed(1)}–${o.t_range[1].toFixed(1)} K`);
    }
    for (const w of result.warnings) this.note(w, "warn");
    this.note(`Consistency check finished: ${result.overlaps.length} overlaps, ${result.warnings.length} warnings`);
  }

  async compareModels() {
    if (this.datasets.length === 0) return;
    const result = await this.run("Comparison", () =>
      worker<CompareResponse>("model.compare", {
        datasets: this.activeDatasets(),
        models: this.fittedModels(),
        include_references: true,
      }),
    );
    if (result) {
      this.comparison = result;
      this.note(`Compared ${result.models.length} models on ${this.datasets.length} datasets`);
    }
  }

  invalidateResults() {
    this.consistency = null;
    this.comparison = null;
    for (const c of this.candidates) {
      c.fit = null;
      c.study = null;
    }
    this.selection = null;
  }
}

export const project = new Project();
