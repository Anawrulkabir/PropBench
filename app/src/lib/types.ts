// JSON shapes of the worker operations (propbench.api); SI units throughout, null where a value is undefined.

export interface Provenance {
  doi: string | null;
  citation: string | null;
  method: string | null;
  purity: string | null;
  notes: string | null;
}

/** `Dataset.to_dict()` (schema version 1). */
export interface Dataset {
  schema_version: number;
  name: string;
  fluid: string;
  quantity: string;
  temperature: number[];
  values: number[];
  pressure: number[] | null;
  molar_density: number[] | null;
  expanded_uncertainty: number[] | null;
  coverage_factor: number;
  phase: string[] | null;
  point_ids: number[];
  provenance: Partial<Provenance>;
}

export interface Parameter {
  value: number;
  lower: number | null;
  upper: number | null;
  fixed: boolean;
  unit: string;
  description: string;
}

/** `propbench.models.spec` model spec. */
export interface ModelSpec {
  kind: string;
  name: string;
  fluid: string;
  quantity: string;
  reference: string;
  parameters: Record<string, Parameter>;
  reference_fluid?: string;
  psi_exponents?: number[];
  psi_rhomolar_reducing?: number;
  molar_mass?: number;
}

export interface ModelKind {
  kind: string;
  label: string;
  reference: string;
}

export interface Deviations {
  n: number;
  aard: number | null;
  bias: number | null;
  rms: number | null;
  max_abs: number | null;
}

export interface FitOptions {
  weighted?: boolean;
  scale_factors?: boolean;
  multistart?: number;
  seed?: number;
  fixed?: Record<string, boolean>;
}

export interface FitResponse {
  model: ModelSpec;
  summary: {
    values: Record<string, number>;
    standard_errors: Record<string, number | null>;
    scale_factors: Record<string, number>;
    deviations: Deviations;
    cost: number;
    success: boolean;
    message: string;
    nfev: number;
    starts: number;
    seed: number;
    weighted: boolean;
  };
  criteria: { aic: number | null; bic: number | null };
  correlation?: { names: string[]; matrix: (number | null)[][] };
  n_parameters: number;
  points: {
    dataset: string[];
    point_id: number[];
    temperature: number[];
    molar_density: number[];
    value: number[];
    ard: (number | null)[];
  };
}

export interface CheckEntry {
  name: string;
  fluid: string;
  quantity: string;
  n: number;
  t_range: [number, number];
  p_range: [number, number] | null;
  has_uncertainty: boolean;
  dataset: Dataset;
  phase_mismatches: number[];
  errors: Record<string, string>;
  phases: Record<string, number>;
}

export interface FoldSummary {
  name: string;
  success: boolean;
  values: Record<string, number>;
  train: Deviations;
  test: Deviations;
  message: string;
}

export interface CrossValidationSummary {
  method: string;
  seed: number;
  pooled: Deviations;
  folds: FoldSummary[];
  parameters: Record<string, { mean: number | null; std: number | null }>;
  points?: { fold: string[]; dataset: string[]; point_id: number[]; ard: (number | null)[] };
}

export interface PhysicsCheck {
  name: string;
  passed: boolean;
  n_states: number;
  message: string;
  violations: [number, number][];
  not_evaluated: number;
}

export interface StudyResponse {
  seed: number;
  cross_validation: Record<string, CrossValidationSummary>;
  physics?: PhysicsCheck[];
}

export interface SelectionRule {
  metric: string;
  validation: string;
  tie_tolerance: number;
  require_physics: boolean;
  notes: string;
}

export interface SelectionResponse {
  chosen: string;
  ranking: string[];
  excluded: string[];
  rule_sha256: string;
  reason: string;
}

export interface Preview {
  rows: string[][];
  sheets: string[];
  sheet: string | null;
  delimiter: string | null;
  thermoml: boolean;
}

export interface ColumnSpec {
  column: string;
  role: string;
  unit?: string;
  uncertainty_kind?: string;
}

export interface ImportMapping {
  kind: "propbench.import-mapping";
  version: 1;
  quantity: string;
  columns: ColumnSpec[];
  coverage_factor: number;
  header_row: number;
  first_data_row?: number | null;
  sheet?: string | null;
  saturation?: "liquid" | "vapor" | null;
}

export interface OffsetResult {
  dataset: string;
  reference: string;
  n: number;
  offset: number;
  ci95: [number, number];
  u_reference: number;
  ci95_total: [number, number];
  birge: number | null;
  significant: boolean;
  extrapolated: number;
}

export interface ComparisonPoint {
  a: string;
  b: string;
  point_id: number;
  temperature: number;
  delta_t: number;
  pressure: number;
  value: number;
  trend_value: number;
  difference: number;
  u_combined: number;
  z: number | null;
  consistent: boolean;
  extrapolated: boolean;
  bound?: number | null;
  bound_kind?: "at least" | "at most" | null;
}

export interface TrendCheckResult {
  a: string;
  b: string;
  temperature: number;
  slope_sign: number;
  violations: [number, number][];
  passed: boolean;
}

export interface IsothermPlot {
  temperature: number;
  phase: string;
  reference: string;
  other: string;
  points: {
    dataset: string;
    pressure: number[];
    value: number[];
    expanded_uncertainty: number[] | null;
    point_ids: number[];
  }[];
  trend: { pressure: number[]; value: number[] };
  trend_range: [number, number];
}

export interface ConsistencyResponse {
  overlaps: { a: string; b: string; t_range: [number, number]; a_points: number[]; b_points: number[] }[];
  comparisons: ComparisonPoint[];
  trend_checks: TrendCheckResult[];
  offsets: OffsetResult[];
  z_scores: { dataset: string; reference: string; n_outside: number; max_abs: number | null; z: (number | null)[] }[];
  warnings: string[];
  models: string[];
  plots: IsothermPlot[];
}

export interface CompareResponse {
  models: string[];
  rows: {
    model: string;
    dataset: string;
    deviations: Deviations;
    not_evaluated: number;
    point_ids: number[] | null;
    ard: (number | null)[] | null;
  }[];
}
