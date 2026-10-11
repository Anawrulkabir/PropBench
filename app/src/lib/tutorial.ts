// The guided CF3I tutorial (README M3 acceptance: a new user completes it unaided). Each step explains one action,
// can do it for the user, and is ticked off from the project's state, so steps done through the menus count too.

export interface TutorialState {
  datasets: { name: string }[];
  checks: Record<string, unknown>;
  consistency: unknown;
  candidates: { start: { kind: string }; fit: unknown; study: unknown }[];
  locked: unknown;
  comparison: unknown;
  log: { text: string }[];
  filePath: string | null;
}

export interface Step {
  id: string;
  title: string;
  text: string;
  action: string;
  done: (s: TutorialState) => boolean;
}

export const STEPS: Step[] = [
  {
    id: "data",
    title: "Load the published data",
    text: "Tuhin et al. (2024) measured CF3I in the liquid and the vapour; Duan et al. (1999) along the saturated liquid. Each dataset keeps its DOI and stated uncertainty.",
    action: "Load data",
    done: (s) => s.datasets.length >= 3,
  },
  {
    id: "check",
    title: "Check the data",
    text: "PropBench converts to SI, assigns a phase to every point from the reference equation of state and flags points outside its range.",
    action: "Run the data check",
    done: (s) => Object.keys(s.checks).length > 0,
  },
  {
    id: "consistency",
    title: "Find where datasets disagree",
    text: "Where two sources overlap, PropBench compares them without any model. At 333 K the 2024 and 1999 liquid data differ by at least 4.9 %, more than both stated uncertainties allow.",
    action: "Check consistency",
    done: (s) => s.consistency !== null && s.consistency !== undefined,
  },
  {
    id: "model",
    title: "Add a model",
    text: "Extended corresponding states (ECS) predicts CF3I from a well-known reference fluid. R134a is the usual reference; the shape function ψ is fitted.",
    action: "Add ECS (R134a)",
    done: (s) => s.candidates.some((c) => c.start.kind === "ecs_viscosity"),
  },
  {
    id: "fit",
    title: "Fit the model",
    text: "Weighted least squares in relative deviation, with the stated uncertainties as weights. The fitting tab shows parameters, their errors and the deviations.",
    action: "Fit",
    done: (s) => s.candidates.some((c) => c.fit),
  },
  {
    id: "validate",
    title: "Lock the selection rule, then validate",
    text: "The rule that chooses the model is fixed before any validation result is seen. Leave-one-state-out refits the model without each measured state and predicts it.",
    action: "Lock and validate",
    done: (s) => !!s.locked && s.candidates.some((c) => c.study),
  },
  {
    id: "compare",
    title: "Compare with the NIST reference model",
    text: "NISTIR 8209 (Huber 2018) is the published reference model for CF3I; PropBench reproduces its check values exactly. Compare its deviations with your model's.",
    action: "Compare models",
    done: (s) => s.comparison !== null && s.comparison !== undefined,
  },
  {
    id: "figure",
    title: "Export a publication figure",
    text: "The graph studio exports journal-sized figures (PDF, SVG, PNG up to 2500 dpi) with the legend inside the axes.",
    action: "Open the graph studio",
    done: (s) => s.log.some((l) => l.text.startsWith("Figure exported") || l.text.startsWith("Figure set exported")),
  },
  {
    id: "save",
    title: "Save the project",
    text: "Everything — data, masks, models, the locked rule, results and the audit log — is saved in one .pbp file.",
    action: "Save",
    done: (s) => s.filePath !== null,
  },
];

/** Index of the first step not yet done (STEPS.length when all are done). */
export function currentStep(s: TutorialState): number {
  const i = STEPS.findIndex((step) => !step.done(s));
  return i === -1 ? STEPS.length : i;
}
