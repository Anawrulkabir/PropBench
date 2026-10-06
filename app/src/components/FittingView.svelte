<script lang="ts">
  // Curve fitting (design/mockups/13_Fitting): equation, parameters (value, SD, free/fixed, bounds), data and
  // weights, diagnostics (χ², AIC/BIC, correlations) and residuals of one candidate model.
  import { project } from "../lib/project.svelte";
  import { fmt, pct } from "../lib/quantities";
  import { deviationSeries, freeParameters, typicalUncertainty } from "../lib/study";
  import ScatterPlot from "./ScatterPlot.svelte";

  const EQUATIONS: Record<string, string[]> = {
    ecs_viscosity: ["η(T, ρ) = k·η₀(T) + F_η(T, ρ) · Δη_ref(T₀, ρ₀·ψ)", "ψ(δ) = ψ₀ + ψ₁·δ (+ ψ₂·δ²),   δ = ρ/ρ_red"],
    ecs_conductivity: ["λ(T, ρ) = λ*(T) + F_λ · λ_ref^r(T₀, ρ₀·χ) + λ_c(T, ρ)", "χ(δ) = χ₀ + χ₁·δ,   f_int = a₀ + a₁·T"],
    chung_viscosity: ["η = η*·(36.344·√(M·T_c)/V_c^(2/3)) ... (Chung et al. 1988)", "predictive: no free parameters unless freed below"],
    lj_dilute_viscosity: ["η₀(T) = k · 26.692·√(M·T) / (σ²·Ω(2,2)*(T*))", "Chapman–Enskog, Neufeld collision integral"],
    coolprop_transport: ["CoolProp reference correlation", "comparison only, no parameters"],
  };

  let selectedRow = $state<string | null>(null);

  const c = $derived(
    (project.selected?.type === "candidate" ? project.candidate(project.selected.id) : undefined) ?? project.candidates[0],
  );
  const free = $derived(c ? freeParameters(c) : []);
  const fit = $derived(c?.fit ?? null);
  const n = $derived(fit?.summary.deviations.n ?? project.activeDatasets().reduce((s, d) => s + d.values.length, 0));
  const reducedChi2 = $derived(fit ? (2 * fit.summary.cost) / Math.max(1, n - fit.n_parameters) : null);
  const u = $derived(typicalUncertainty(project.activeDatasets()));

  function isFixed(name: string): boolean {
    return c ? (c.fixed[name] ?? c.start.parameters[name].fixed) : true;
  }
  function invalidate() {
    if (!c) return;
    c.fit = null;
    c.study = null;
    project.selection = null;
  }
  function toggleFixed(name: string) {
    if (!c) return;
    c.fixed[name] = !isFixed(name);
    invalidate();
  }
  function setBound(name: string, which: "lower" | "upper", text: string) {
    if (!c) return;
    const v = text.trim() === "" ? null : Number(text);
    if (v !== null && !Number.isFinite(v)) return;
    c.start.parameters[name][which] = v;
    invalidate();
  }
  function setStart(name: string, text: string) {
    if (!c) return;
    const v = Number(text);
    if (Number.isFinite(v)) {
      c.start.parameters[name].value = v;
      invalidate();
    }
  }
</script>

<div class="view">
  {#if !c}
    <div class="empty well">Add a candidate model on the Models tab first.</div>
  {:else}
    <div class="cols">
      <div class="col">
        <fieldset class="group">
          <legend>Equation (built-in: {c.start.name})</legend>
          <div class="well eq mono">
            {#each EQUATIONS[c.start.kind] ?? [c.start.name] as line (line)}<div>{line}</div>{/each}
          </div>
          <div class="row">
            <button class="btn" disabled title="User equations: M3a">Edit equation…</button>
            <button class="btn" disabled title="User equations: M3a">New user function…</button>
            <span class="spacer"></span>
            <span class="muted">{c.start.reference}</span>
          </div>
        </fieldset>

        <fieldset class="group">
          <legend>Parameters</legend>
          <div class="well scrollx">
            <table class="grid">
              <thead>
                <tr><th>Parameter</th><th>Start</th><th>Value</th><th>SD</th><th>Status</th><th>Lower</th><th>Upper</th></tr>
              </thead>
              <tbody>
                {#each Object.entries(c.start.parameters) as [name, p] (name)}
                  <tr class="clickable" class:sel={selectedRow === name} onclick={() => (selectedRow = name)}>
                    <td title={p.description}>{name}</td>
                    <td><input class="field num cell" value={p.value} onchange={(e) => setStart(name, (e.currentTarget as HTMLInputElement).value)} aria-label="Start of {name}" /></td>
                    <td class="num">{fit && name in fit.summary.values ? fmt(fit.summary.values[name], 6) : "–"}</td>
                    <td class="num">{fit && name in fit.summary.standard_errors ? fmt(fit.summary.standard_errors[name], 3) : "–"}</td>
                    <td class:ok={!isFixed(name)}>{isFixed(name) ? "fixed" : "free"}</td>
                    <td><input class="field num cell" value={p.lower ?? ""} onchange={(e) => setBound(name, "lower", (e.currentTarget as HTMLInputElement).value)} aria-label="Lower bound of {name}" /></td>
                    <td><input class="field num cell" value={p.upper ?? ""} onchange={(e) => setBound(name, "upper", (e.currentTarget as HTMLInputElement).value)} aria-label="Upper bound of {name}" /></td>
                  </tr>
                {/each}
                {#each Object.entries(fit?.summary.scale_factors ?? {}) as [name, v] (name)}
                  <tr><td>c ({name})</td><td></td><td class="num">{fmt(v, 6)}</td><td></td><td>per dataset</td><td>0.5</td><td>2</td></tr>
                {/each}
              </tbody>
            </table>
          </div>
          <div class="row">
            <button class="btn" onclick={() => selectedRow && toggleFixed(selectedRow)} disabled={!selectedRow}>
              {selectedRow && isFixed(selectedRow) ? "Free" : "Fix"}
            </button>
            <label class="row"><input type="checkbox" bind:checked={project.settings.scaleFactors} /> scale factor per dataset</label>
            <span class="spacer"></span>
            <span class="muted">{free.length} free</span>
            <button class="btn default" onclick={() => project.fit(c.id)} disabled={!!project.busy}>{project.busy?.startsWith("Fit") ? "Fitting…" : "Fit"}</button>
          </div>
        </fieldset>

        <fieldset class="group">
          <legend>Residuals</legend>
          {#if fit}
            <div class="well plotbox">
              <ScatterPlot series={deviationSeries(fit)} xLabel="Temperature (K)" yLabel="residual (%)" zeroLine band={u === null ? null : [-u, u]} bandLabel="median expanded U" height={190} />
            </div>
          {:else}
            <p class="muted">Fit the model to see its residuals.</p>
          {/if}
        </fieldset>
      </div>

      <div class="col">
        <fieldset class="group">
          <legend>Data and weights</legend>
          <div class="form">
            <span>Datasets</span>
            <span class="mono">{project.activeDatasets().map((d) => `${d.name} (${d.values.length})`).join(", ") || "none"}</span>
            <label for="w">Weighting</label>
            <select id="w" class="field" value={project.settings.weighted ? "u" : "none"} onchange={(e) => { project.settings.weighted = (e.currentTarget as HTMLSelectElement).value === "u"; invalidate(); }}>
              <option value="u">1 / u², stated uncertainty</option>
              <option value="none">equal weights</option>
            </select>
            <label for="ms">Multi-start</label>
            <input id="ms" class="field num" type="number" min="0" max="50" bind:value={project.settings.multistart} />
            <label for="sd">Seed</label>
            <input id="sd" class="field num" type="number" min="0" bind:value={project.settings.seed} />
          </div>
          <p class="muted">Masked worksheet rows are left out. Global fit: parameters shared by all datasets; optional scale factor per dataset (first dataset is the reference).</p>
        </fieldset>

        <fieldset class="group">
          <legend>Diagnostics</legend>
          <table class="props">
            <tbody>
              <tr><td>Weights</td><td>{project.settings.weighted ? "1 / u(η)²" : "equal"}</td></tr>
              <tr><td>Reduced χ²</td><td>{reducedChi2 === null ? "[after fit]" : fmt(reducedChi2, 4)}</td></tr>
              <tr><td>AIC / BIC</td><td>{fit ? `${fmt(fit.criteria.aic)} / ${fmt(fit.criteria.bic)}` : "[after fit]"}</td></tr>
              <tr><td>AARD / bias</td><td>{fit ? `${pct(fit.summary.deviations.aard, 3)} / ${pct(fit.summary.deviations.bias, 3)} %` : "[after fit]"}</td></tr>
              <tr><td>Converged</td><td>{fit ? (fit.summary.success ? `yes (${fit.summary.nfev} evaluations)` : fit.summary.message) : "[after fit]"}</td></tr>
            </tbody>
          </table>
          {#if fit?.correlation && fit.correlation.names.length > 1}
            <p class="sub">Correlation matrix</p>
            <table class="grid corr">
              <thead><tr><th></th>{#each fit.correlation.names as nm (nm)}<th>{nm}</th>{/each}</tr></thead>
              <tbody>
                {#each fit.correlation.matrix as row, i (i)}
                  <tr>
                    <th>{fit.correlation.names[i]}</th>
                    {#each row as v, j (j)}<td class="num" class:strong={i !== j && v !== null && Math.abs(v) > 0.95}>{v === null ? "–" : v.toFixed(3)}</td>{/each}
                  </tr>
                {/each}
              </tbody>
            </table>
            <p class="muted">|r| &gt; 0.95 (bold): the parameters are hard to determine separately from these data.</p>
          {/if}
        </fieldset>

        <fieldset class="group">
          <legend>Uncertainty budget (GUM)</legend>
          <table class="grid">
            <thead><tr><th>Input</th><th>Contribution u (%)</th><th>Share of variance (%)</th></tr></thead>
            <tbody>
              {#each ["Pressure drop ΔP", "Flow rate q", "Capillary radius a", "Tube length L", "Temperature T", "Pressure p"] as input (input)}
                <tr><td>{input}</td><td class="muted">[value]</td><td class="muted">[value]</td></tr>
              {/each}
            </tbody>
          </table>
          <div class="row">
            <span class="muted">Uncertainty propagation (linear and Monte Carlo, JCGM 100/101): M3a.</span>
            <span class="spacer"></span>
            <button class="btn" disabled>Linear propagation</button>
            <button class="btn" disabled>Monte Carlo…</button>
          </div>
        </fieldset>
      </div>
    </div>
  {/if}
</div>

<style>
  .view {
    height: 100%;
    min-height: 0;
    overflow: auto;
  }
  .cols {
    display: grid;
    grid-template-columns: minmax(0, 1.15fr) minmax(0, 1fr);
    gap: 8px;
  }
  .col {
    display: grid;
    gap: 8px;
    align-content: start;
    min-width: 0;
  }
  .scrollx {
    overflow-x: auto;
  }
  @media (max-width: 1250px) {
    .cols {
      grid-template-columns: minmax(0, 1fr);
    }
  }
  .col fieldset {
    display: grid;
    gap: 6px;
  }
  .eq {
    padding: 6px 8px;
    font-size: 12px;
    line-height: 1.6;
  }
  .cell {
    width: 76px;
  }
  .form {
    display: grid;
    grid-template-columns: auto 1fr;
    gap: 5px 8px;
    align-items: center;
  }
  .plotbox {
    padding: 4px;
  }
  .sub {
    margin: 6px 0 2px;
  }
  .corr td.strong {
    font-weight: 700;
    color: var(--error);
  }
</style>
