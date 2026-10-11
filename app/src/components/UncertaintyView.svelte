<script lang="ts">
  // Uncertainty budget (README §2e.6): GUM linear propagation (JCGM 100) with sensitivity coefficients,
  // contributions, Welch–Satterthwaite degrees of freedom and coverage factor; Monte Carlo (JCGM 101) with a seed.
  import { errorMessage, worker } from "../lib/api";
  import { project } from "../lib/project.svelte";
  import { fmt } from "../lib/quantities";

  interface InputRow {
    name: string;
    value: number;
    u: number;
    dof: number | null;
    distribution: "normal" | "rectangular" | "triangular";
    note: string;
  }
  interface Budget {
    value: number;
    u: number;
    dof: number | null;
    k: number;
    U: number;
    p: number;
    interval: [number, number];
    budget: { name: string; value: number; u: number; dof: number | null; sensitivity: number; contribution: number; index: number }[];
  }
  interface MonteCarlo {
    value: number;
    u: number;
    interval: [number, number];
    draws: number;
    seed: number;
    histogram: number[];
    edges: number[];
  }

  let model = $state("V**2 / (R0 * (1 + alpha * (t - t0)))");
  let unit = $state("W");
  let inputs = $state<InputRow[]>([
    { name: "V", value: 10.0, u: 0.01, dof: null, distribution: "normal", note: "voltage / V" },
    { name: "R0", value: 100.0, u: 0.05, dof: 10, distribution: "normal", note: "resistance at t0 / Ω" },
    { name: "alpha", value: 0.0039, u: 0.00002, dof: null, distribution: "rectangular", note: "temperature coefficient / K⁻¹" },
    { name: "t", value: 25.0, u: 0.1, dof: null, distribution: "normal", note: "temperature / °C" },
    { name: "t0", value: 20.0, u: 0, dof: null, distribution: "normal", note: "reference temperature / °C" },
  ]);
  let correlations = $state<{ a: string; b: string; r: number }[]>([]);
  let p = $state(0.9545);
  let draws = $state(200000);
  let seed = $state(0);
  let budget = $state<Budget | null>(null);
  let mc = $state<MonteCarlo | null>(null);
  let error = $state("");
  let busy = $state(false);

  function loadH1() {
    model = "ls + d - ls * (dalpha * theta + alpha_s * dtheta)";
    unit = "mm";
    inputs = [
      { name: "ls", value: 50.000623, u: 25e-6, dof: 18, distribution: "normal", note: "length of the standard / mm (H.1.3.1)" },
      { name: "d", value: 215e-6, u: 9.7e-6, dof: 25.6, distribution: "normal", note: "measured difference / mm (H.1.3.2)" },
      { name: "alpha_s", value: 11.5e-6, u: 1.2e-6, dof: null, distribution: "rectangular", note: "expansion coefficient / °C⁻¹" },
      { name: "theta", value: -0.1, u: 0.41, dof: null, distribution: "normal", note: "deviation from 20 °C / °C" },
      { name: "dalpha", value: 0, u: 0.58e-6, dof: 50, distribution: "rectangular", note: "difference of α / °C⁻¹" },
      { name: "dtheta", value: 0, u: 0.029, dof: 2, distribution: "rectangular", note: "difference of temperatures / °C" },
    ];
    correlations = [];
    p = 0.99;
    budget = null;
    mc = null;
  }

  const payload = () => ({
    model,
    inputs: inputs.map((i) => ({ name: i.name, value: i.value, u: i.u, dof: i.dof, distribution: i.distribution })),
    correlations,
    p,
  });

  async function linear() {
    busy = true;
    error = "";
    try {
      budget = await worker<Budget>("gum.linear", payload());
      project.note(`Uncertainty budget: y = ${fmt(budget.value, 9)} ${unit}, u_c = ${fmt(budget.u, 3)}, U = ${fmt(budget.U, 3)} (k = ${budget.k.toFixed(2)})`);
    } catch (err) {
      error = errorMessage(err);
    } finally {
      busy = false;
    }
  }

  async function monteCarlo() {
    busy = true;
    error = "";
    try {
      mc = await worker<MonteCarlo>("gum.montecarlo", { ...payload(), draws, seed });
    } catch (err) {
      error = errorMessage(err);
    } finally {
      busy = false;
    }
  }

  function save() {
    if (!budget) return;
    const label = window.prompt("Name of this budget", model);
    if (label) project.tools.budgets.push({ label, model, unit, inputs: $state.snapshot(inputs), correlations: $state.snapshot(correlations), p, budget: $state.snapshot(budget) });
  }

  const maxBin = $derived(mc ? Math.max(...mc.histogram) : 1);
</script>

<div class="gum">
  <div class="left">
    <fieldset class="group">
      <legend>Measurement model</legend>
      <div class="row"><span class="mono">y =</span><input class="field grow mono" bind:value={model} aria-label="Model" /><input class="field unit" bind:value={unit} aria-label="Unit of y" /></div>
      <div class="row"><button class="btn" onclick={loadH1}>Load JCGM 100 example H.1 (end gauge)</button></div>
    </fieldset>
    <fieldset class="group">
      <legend>Input quantities</legend>
      <table class="grid">
        <thead><tr><th>Name</th><th>Value</th><th>u (standard)</th><th>ν</th><th>Distribution</th><th>Note</th><th></th></tr></thead>
        <tbody>
          {#each inputs as i, n (n)}
            <tr>
              <td><input class="field name" bind:value={i.name} /></td>
              <td><input class="field cell" type="number" step="any" bind:value={i.value} /></td>
              <td><input class="field cell" type="number" step="any" min="0" bind:value={i.u} /></td>
              <td><input class="field small" type="number" step="any" min="1" bind:value={i.dof} placeholder="∞" /></td>
              <td><select class="field" bind:value={i.distribution}><option>normal</option><option>rectangular</option><option>triangular</option></select></td>
              <td><input class="field note" bind:value={i.note} /></td>
              <td><button class="btn" onclick={() => inputs.splice(n, 1)} aria-label="Remove {i.name}">×</button></td>
            </tr>
          {/each}
        </tbody>
      </table>
      <div class="row">
        <button class="btn" onclick={() => inputs.push({ name: `x${inputs.length + 1}`, value: 0, u: 0, dof: null, distribution: "normal", note: "" })}>Add input</button>
        <button class="btn" onclick={() => correlations.push({ a: inputs[0]?.name ?? "", b: inputs[1]?.name ?? "", r: 0 })} disabled={inputs.length < 2}>Add correlation</button>
      </div>
      {#each correlations as c, n (n)}
        <div class="row">
          r(<select class="field" bind:value={c.a}>{#each inputs as i (i.name)}<option>{i.name}</option>{/each}</select>,
          <select class="field" bind:value={c.b}>{#each inputs as i (i.name)}<option>{i.name}</option>{/each}</select>) =
          <input class="field small" type="number" min="-1" max="1" step="0.01" bind:value={c.r} />
          <button class="btn" onclick={() => correlations.splice(n, 1)}>×</button>
        </div>
      {/each}
    </fieldset>
    <fieldset class="group">
      <legend>Propagation</legend>
      <div class="row">
        <label class="row">Coverage
          <select class="field" bind:value={p}><option value={0.6827}>68.27 %</option><option value={0.95}>95 %</option><option value={0.9545}>95.45 %</option><option value={0.99}>99 %</option></select>
        </label>
        <button class="btn default" onclick={linear} disabled={busy}>GUM (linear)</button>
        <span class="spacer"></span>
        <label class="row">Draws <input class="field cell" type="number" min="1000" step="1000" bind:value={draws} /></label>
        <label class="row">Seed <input class="field small" type="number" bind:value={seed} /></label>
        <button class="btn" onclick={monteCarlo} disabled={busy}>Monte Carlo (JCGM 101)</button>
      </div>
    </fieldset>
    {#if error}<div class="notice err">{error}</div>{/if}
  </div>
  <div class="right">
    {#if budget}
      <fieldset class="group">
        <legend>Uncertainty budget</legend>
        <table class="grid">
          <thead><tr><th>Quantity</th><th>Value</th><th>u(xᵢ)</th><th>νᵢ</th><th>cᵢ</th><th>|cᵢ| u(xᵢ)</th><th>Index</th></tr></thead>
          <tbody>
            {#each budget.budget as b (b.name)}
              <tr>
                <td class="mono">{b.name}</td><td class="num">{fmt(b.value, 8)}</td><td class="num">{fmt(b.u, 3)}</td><td class="num">{b.dof ?? "∞"}</td>
                <td class="num">{fmt(b.sensitivity, 4)}</td><td class="num">{fmt(b.contribution, 3)}</td>
                <td><div class="bar" style="width: {Math.round(100 * b.index)}%"></div>{(100 * b.index).toFixed(1)} %</td>
              </tr>
            {/each}
          </tbody>
        </table>
        <p class="result">
          y = {fmt(budget.value, 10)} {unit} · u_c = {fmt(budget.u, 3)} {unit} · ν_eff = {budget.dof === null ? "∞" : budget.dof.toFixed(1)} ·
          k = {budget.k.toFixed(2)} · U = {fmt(budget.U, 3)} {unit} ({(100 * budget.p).toFixed(2)} %)
        </p>
        <div class="row"><span class="spacer"></span><button class="btn" onclick={save}>Save budget…</button></div>
      </fieldset>
    {/if}
    {#if mc}
      <fieldset class="group">
        <legend>Monte Carlo ({mc.draws.toLocaleString()} draws, seed {mc.seed})</legend>
        <p>y = {fmt(mc.value, 10)} {unit} · u = {fmt(mc.u, 3)} {unit} · {(100 * p).toFixed(2)} % interval [{fmt(mc.interval[0], 10)}, {fmt(mc.interval[1], 10)}]</p>
        <svg viewBox="0 0 600 160" class="hist" role="img" aria-label="Distribution of the output">
          {#each mc.histogram as h, i (i)}
            {@const x = (600 * i) / mc.histogram.length}
            {@const inside = mc.edges[i] >= mc.interval[0] && mc.edges[i + 1] <= mc.interval[1]}
            <rect x={x} y={150 - (140 * h) / maxBin} width={600 / mc.histogram.length - 1} height={(140 * h) / maxBin} fill={inside ? "#1f5fa8" : "#9bb3d6"} />
          {/each}
          <line x1="0" x2="600" y1="150.5" y2="150.5" stroke="#000" />
        </svg>
        {#if budget}<p class="muted">GUM: u_c = {fmt(budget.u, 3)}; Monte Carlo: u = {fmt(mc.u, 3)} ({((100 * (mc.u - budget.u)) / budget.u).toFixed(1)} %). Large differences mean the linear model is not adequate.</p>{/if}
      </fieldset>
    {/if}
    {#if !budget && !mc}<div class="empty well">Enter the measurement model and its inputs, then propagate. Load the JCGM 100 H.1 example to see the method reproduce u_c = 32 nm and U₉₉ = 93 nm.</div>{/if}
  </div>
</div>

<style>
  .gum {
    display: grid;
    grid-template-columns: repeat(auto-fit, minmax(560px, 1fr));
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
  .unit {
    width: 60px;
  }
  .name {
    width: 70px;
  }
  .cell {
    width: 96px;
  }
  .small {
    width: 56px;
  }
  .note {
    width: 150px;
  }
  .bar {
    display: inline-block;
    height: 8px;
    margin-right: 4px;
    background: #1f5fa8;
  }
  .result {
    font-weight: 700;
  }
  .hist {
    width: 100%;
    height: auto;
  }
  .err {
    color: var(--error);
  }
</style>
