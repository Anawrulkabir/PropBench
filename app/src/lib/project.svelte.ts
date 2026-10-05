// The open project: datasets, candidate models, studies and the output log. All computation goes through the
// worker (`worker()` → Tauri → pb-engine → Python); this module only keeps state and sequences the calls.

import { errorMessage, fileToBase64, worker } from "./api";
import { type Candidate, commonTarget, selectionCandidates, uniqueName } from "./study";
import type {
  CheckEntry,
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

export type View = "data" | "fit" | "study" | "results" | "calculator";

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
    methods: ["loso"],
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
    validation: "loso",
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
      this.note(`${label} failed: ${errorMessage(err)}`, "error");
      return null;
    } finally {
      this.busy = null;
    }
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
      const names = this.datasets.map((d) => d.name);
      for (const d of result.datasets) {
        d.name = uniqueName(names, d.name);
        names.push(d.name);
        this.datasets.push(d);
        this.note(`Imported ${d.name}: ${d.values.length} points of ${d.quantity} (${d.fluid})`);
      }
      for (const w of result.warnings) this.note(w, "warn");
      this.selection = null;
      await this.checkData();
      return result.datasets.length;
    });
  }

  removeDataset(name: string) {
    this.datasets = this.datasets.filter((d) => d.name !== name);
    delete this.checks[name];
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
      worker<FitResponse>("model.fit", { model: c.start, datasets: this.datasets, options: this.fitOptions(c) }),
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
    for (const c of [...this.candidates]) await this.fit(c.id);
  }

  // --- validation and selection ---

  async validate(id: string) {
    const c = this.candidate(id);
    if (!c) return;
    const s = this.settings;
    const result = await this.run(`Validate ${c.label}`, () =>
      worker<StudyResponse>("study.validate", {
        model: c.start,
        datasets: this.datasets,
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
    for (const c of [...this.candidates]) {
      await this.fit(c.id);
      await this.validate(c.id);
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
      this.view = "results";
    }
  }

  invalidateResults() {
    for (const c of this.candidates) {
      c.fit = null;
      c.study = null;
    }
    this.selection = null;
  }
}

export const project = new Project();
