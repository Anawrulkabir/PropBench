<script lang="ts">
  // General curve fitting (README §2e.4–5): any equation of worksheet columns, bounds, fixed parameters, weights,
  // global fits with shared and per-dataset parameters, scale factors, multi-start; diagnostics (errors,
  // correlation, χ², AIC/BIC, residuals, outliers) and the F-test of two saved nested fits. The worker computes.
  import { errorMessage, worker } from "../lib/api";
  import type { Line, Series } from "../lib/plot";
  import { project } from "../lib/project.svelte";
  import { fmt } from "../lib/quantities";
  import ScatterPlot from "./ScatterPlot.svelte";

  interface Param {
    name: string;
    value: number;
    lower: number | null;
    upper: number | null;
    fixed: boolean;
    local: boolean;
  }
  interface Result {
    values: Record<string, number>;
    errors: Record<string, number | null>;
    correlation: number[][];
    free: string[];
    scale_factors: Record<string, number>;
    residuals: Record<string, number[]>;
    fitted: Record<string, number[]>;
    studentized: Record<string, number[]>;
    outliers: Record<string, number[]>;
    chi2: number;
    dof: number;
    reduced_chi2: number;
    aic: number;
    bic: number;
    r2: number;
    n: number;
    success: boolean;
    message: string;
    starts: number;
  }
  interface Saved {
    label: string;
    equation: string;
    result: Result;
  }

  const FUNCS = new Set(["exp", "log", "ln", "log10", "sqrt", "abs", "sin", "cos", "tan", "sinh", "cosh", "tanh", "minimum", "maximum", "where", "eos", "pi", "e", "R", "NA", "kB", "and", "or", "not", "if", "else", "fluid"]);

  let equation = $state("a * exp(b / T)");
  let xVars = $state("T");
  let yCol = $state("y");
  let sigmaCol = $state("u");
  let chosen = $state<string[]>(project.datasets.slice(0, 1).map((d) => d.name));
  let params = $state<Param[]>([
    { name: "a", value: 1e-5, lower: 0, upper: null, fixed: false, local: false },
    { name: "b", value: 500, lower: null, upper: null, fixed: false, local: false },
  ]);
  let scaleFactors = $state(false);
  let multistart = $state(0);
  let seed = $state(0);
  let result = $state<Result | null>(null);
  let error = $state("");
  let busy = $state(false);
  let ftest = $state<{ F: number; df1: number; df2: number; p: number } | null>(null);
  let pickA = $state(0);
  let pickB = $state(1);

  const saved = $derived(project.tools.curvefits as Saved[]);
  const variables = $derived(xVars.split(/[\s,]+/).filter(Boolean));

  /** Names in the equation that are not variables or functions: proposed as parameters (editable). */
  function detect() {
    const found = [...new Set(equation.match(/[A-Za-z_][A-Za-z0-9_]*/g) ?? [])].filter((n) => !FUNCS.has(n) && !variables.includes(n));
    const keep = params.filter((p) => found.includes(p.name));
    for (const n of found) if (!keep.some((p) => p.name === n)) keep.push({ name: n, value: 1, lower: null, upper: null, fixed: false, local: false });
    params = keep;
  }

  async function run() {
    busy = true;
    error = "";
    ftest = null;
    try {
      const series = project.activeDatasets().filter((d) => chosen.includes(d.name)).map((d) => ({
        dataset: d,
        formulas: project.worksheets[d.name]?.formulas ?? [],
        x: variables,
        y: yCol,
        sigma: sigmaCol || null,
      }));
      if (!series.length) throw new Error("choose at least one dataset");
      result = await worker<Result>("curvefit.fit", {
        equation,
        series,
        parameters: Object.fromEntries(params.map((p) => [p.name, { value: p.value, lower: p.lower, upper: p.upper, fixed: p.fixed }])),
        local: params.filter((p) => p.local).map((p) => p.name),
        scale_factors: scaleFactors,
        weighted: !!sigmaCol,
        multistart,
        seed,
      });
      project.note(`Curve fit ${equation}: χ²/ν = ${fmt(result.reduced_chi2, 4)}, R² = ${fmt(result.r2, 6)}, ${result.n} points`);
    } catch (err) {
      error = errorMessage(err);
      project.note(`Curve fit failed: ${error}`, "error");
    } finally {
      busy = false;
    }
  }

  function save() {
    if (!result) return;
    const label = window.prompt("Name of this fit", `${equation} (${result.free.length} parameters)`);
    if (!label) return;
    project.tools.curvefits.push({ label, equation, result: $state.snapshot(result) });
  }

  async function compare() {
    const a = saved[pickA];
    const b = saved[pickB];
    if (!a || !b) return;
    const [simple, full] = a.result.free.length < b.result.free.length ? [a, b] : [b, a];
    try {
      ftest = await worker("curvefit.ftest", { simple: simple.result, full: full.result });
    } catch (err) {
      error = errorMessage(err);
    }
  }

  const data = $derived(project.activeDatasets().filter((d) => chosen.includes(d.name)));
  const plotted = $derived.by(() => {
    if (!result || variables.length !== 1 || variables[0] !== "T") return { points: [] as Series[], fits: [] as Line[], resid: [] as Series[] };
    const points: Series[] = [];
    const fits: Line[] = [];
    const resid: Series[] = [];
    for (const d of data) {
      const fitted = result.fitted[d.name];
      if (!fitted) continue;
      const order = d.temperature.map((_, i) => i).sort((i, j) => d.temperature[i] - d.temperature[j]);
      points.push({ name: d.name, x: d.temperature, y: d.values });
      if (fitted.length === d.temperature.length) {
        fits.push({ name: `fit: ${d.name}`, x: order.map((i) => d.temperature[i]), y: order.map((i) => fitted[i]) });
        resid.push({ name: d.name, x: d.temperature, y: result.studentized[d.name] });
      }
    }
    return { points, fits, resid };
  });
</script>

<div class="cf">
  <div class="left">
    <fieldset class="group">
      <legend>Equation</legend>
      <div class="row"><span class="mono">y =</span><input class="field grow mono" bind:value={equation} onchange={detect} aria-label="Equation" /></div>
      <div class="form">
        <label for="cf-x">Variables</label><input id="cf-x" class="field" bind:value={xVars} onchange={detect} />
        <label for="cf-y">y column</label><input id="cf-y" class="field" bind:value={yCol} />
        <label for="cf-s">σ column</label><input id="cf-s" class="field" bind:value={sigmaCol} placeholder="empty: unweighted" />
      </div>
      <p class="muted">Columns: T p rho y U u u_rel and each dataset's formula columns. Functions: exp log sqrt … eos('Dmass', T, p, fluid='R134a').</p>
    </fieldset>
    <fieldset class="group">
      <legend>Datasets (several = global fit)</legend>
      {#each project.datasets as d (d.name)}
        <label class="row"><input type="checkbox" checked={chosen.includes(d.name)} onchange={(e) => (chosen = (e.currentTarget as HTMLInputElement).checked ? [...chosen, d.name] : chosen.filter((n) => n !== d.name))} />{d.name}</label>
      {:else}<p class="muted">Import data first.</p>{/each}
      <label class="row"><input type="checkbox" bind:checked={scaleFactors} /> Scale factor per dataset (first is the reference)</label>
    </fieldset>
    <fieldset class="group">
      <legend>Parameters</legend>
      <table class="grid">
        <thead><tr><th>Name</th><th>Start</th><th>Lower</th><th>Upper</th><th>Fixed</th><th title="one value per dataset">Local</th></tr></thead>
        <tbody>
          {#each params as p (p.name)}
            <tr>
              <td class="mono">{p.name}</td>
              <td><input class="field cell" type="number" step="any" bind:value={p.value} /></td>
              <td><input class="field cell" type="number" step="any" bind:value={p.lower} /></td>
              <td><input class="field cell" type="number" step="any" bind:value={p.upper} /></td>
              <td><input type="checkbox" bind:checked={p.fixed} /></td>
              <td><input type="checkbox" bind:checked={p.local} /></td>
            </tr>
          {/each}
        </tbody>
      </table>
      <div class="row">
        <button class="btn" onclick={detect}>Detect from equation</button>
        <span class="spacer"></span>
        <label class="row">Multistart <input class="field cell" type="number" min="0" bind:value={multistart} /></label>
        <label class="row">Seed <input class="field cell" type="number" bind:value={seed} /></label>
      </div>
      <div class="row end"><button class="btn default" onclick={run} disabled={busy || !project.datasets.length}>{busy ? "Fitting…" : "Fit"}</button></div>
    </fieldset>
    {#if error}<div class="notice err">{error}</div>{/if}
  </div>
  <div class="right">
    {#if result}
      <fieldset class="group">
        <legend>Result {result.success ? "" : "(not converged)"}</legend>
        <table class="grid">
          <thead><tr><th>Parameter</th><th>Value</th><th>Standard error</th><th>Rel. %</th></tr></thead>
          <tbody>
            {#each Object.entries(result.values) as [n, v] (n)}
              <tr><td class="mono">{n}</td><td class="num">{fmt(v, 7)}</td><td class="num">{result.errors[n] === null ? "fixed" : fmt(result.errors[n], 3)}</td><td class="num">{result.errors[n] ? fmt((100 * (result.errors[n] ?? 0)) / Math.abs(v), 3) : ""}</td></tr>
            {/each}
            {#each Object.entries(result.scale_factors) as [n, v] (n)}<tr><td>scale {n}</td><td class="num">{fmt(v, 6)}</td><td></td><td></td></tr>{/each}
          </tbody>
        </table>
        <p>χ²/ν = {fmt(result.reduced_chi2, 4)} (ν = {result.dof}) · R² = {fmt(result.r2, 6)} · AIC {fmt(result.aic, 5)} · BIC {fmt(result.bic, 5)} · {result.n} points · {result.starts} start{result.starts === 1 ? "" : "s"}</p>
        {#if Object.values(result.outliers).some((o) => o.length)}
          <p class="warn">Possible outliers (|studentised residual| > 3): {Object.entries(result.outliers).filter(([, o]) => o.length).map(([n, o]) => `${n}: rows ${o.map((i) => i + 1).join(", ")}`).join("; ")}</p>
        {/if}
        <div class="row"><span class="spacer"></span><button class="btn" onclick={save}>Save fit…</button></div>
      </fieldset>
      {#if result.free.length > 1}
        <fieldset class="group">
          <legend>Parameter correlation</legend>
          <table class="grid corr">
            <thead><tr><th></th>{#each result.free as n (n)}<th class="mono">{n}</th>{/each}</tr></thead>
            <tbody>
              {#each result.correlation as row, i (i)}
                <tr><th class="mono">{result.free[i]}</th>{#each row as c, j (j)}<td class="num" class:high={i !== j && Math.abs(c) > 0.95}>{c.toFixed(3)}</td>{/each}</tr>
              {/each}
            </tbody>
          </table>
        </fieldset>
      {/if}
      {#if plotted.points.length}
        <ScatterPlot series={plotted.points} lines={plotted.fits} xLabel="T / K" yLabel="y (SI)" height={240} />
        <ScatterPlot series={plotted.resid} xLabel="T / K" yLabel="studentised residual" zeroLine height={170} band={[-3, 3]} bandLabel="±3" />
      {/if}
    {:else}
      <div class="empty well">Write an equation, choose datasets and fit. With several datasets, parameters are shared unless marked Local.</div>
    {/if}
    {#if saved.length >= 2}
      <fieldset class="group">
        <legend>F-test of nested fits</legend>
        <div class="row">
          <select class="field" bind:value={pickA}>{#each saved as s, i (i)}<option value={i}>{s.label}</option>{/each}</select>
          <span>vs</span>
          <select class="field" bind:value={pickB}>{#each saved as s, i (i)}<option value={i}>{s.label}</option>{/each}</select>
          <button class="btn" onclick={compare}>Compare</button>
        </div>
        {#if ftest}<p>F = {fmt(ftest.F, 4)} (df {ftest.df1}, {ftest.df2}), p = {ftest.p.toExponential(2)}: {ftest.p < 0.05 ? "the extra parameters are justified" : "the simpler model is enough"}</p>{/if}
      </fieldset>
    {/if}
  </div>
</div>

<style>
  .cf {
    display: grid;
    grid-template-columns: repeat(auto-fit, minmax(420px, 1fr));
    align-content: start;
    gap: 8px;
    height: 100%;
    min-height: 0;
    overflow: auto;
  }
  .left,
  .right {
    display: grid;
    min-width: 0;
    gap: 6px;
    align-content: start;
  }
  .grow {
    flex: 1;
  }
  .form {
    display: grid;
    grid-template-columns: auto 1fr;
    gap: 4px 6px;
    align-items: center;
    margin-top: 4px;
  }
  .cell {
    width: 78px;
  }
  .end {
    justify-content: flex-end;
  }
  .err {
    color: var(--error);
  }
  .warn {
    color: var(--warn);
  }
  .high {
    color: var(--error);
    font-weight: 700;
  }
</style>
