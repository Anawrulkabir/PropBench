<script lang="ts">
  import { project } from "../lib/project.svelte";
  import { fmt, pct, withError } from "../lib/quantities";
  import { deviationSeries, freeParameters, typicalUncertainty } from "../lib/study";
  import ScatterPlot from "./ScatterPlot.svelte";

  let kind = $state("ecs_viscosity");
  let reference = $state("R134a");
  let useCoolPropEcs = $state(true);

  $effect(() => {
    project.loadKinds();
  });

  const current = $derived(
    project.selected?.type === "candidate" ? project.candidate(project.selected.id) : project.candidates[0],
  );
  const band = $derived.by<[number, number] | null>(() => {
    const u = typicalUncertainty(project.datasets);
    return u === null ? null : [-u, u];
  });

  function add() {
    const ref = kind === "ecs_viscosity" && !useCoolPropEcs ? reference.trim() || "R134a" : null;
    project.addCandidate(kind, ref);
  }

  function isFixed(name: string): boolean {
    if (!current) return true;
    return current.fixed[name] ?? current.start.parameters[name].fixed;
  }

  function setFixed(name: string, fixed: boolean) {
    if (!current) return;
    current.fixed[name] = fixed;
    current.fit = null;
    current.study = null;
    project.selection = null;
  }

  function setStart(name: string, text: string) {
    if (!current) return;
    const v = Number(text);
    if (Number.isFinite(v)) {
      current.start.parameters[name].value = v;
      current.fit = null;
    }
  }
</script>

<div class="view">
  <div class="bar row">
    <b>Models</b>
    <span class="muted">· {project.candidates.length} candidates</span>
    <span class="spacer"></span>
    <select class="field" bind:value={kind} aria-label="Model kind">
      {#each project.kinds as k (k.kind)}<option value={k.kind}>{k.label}</option>{/each}
    </select>
    {#if kind === "ecs_viscosity"}
      <label class="row"><input type="checkbox" bind:checked={useCoolPropEcs} /> published ECS if available</label>
      {#if !useCoolPropEcs}
        <label class="row">reference <input class="field ref" bind:value={reference} /></label>
      {/if}
    {/if}
    <button class="btn" onclick={add} disabled={!!project.busy || !project.datasets.length}>Add model</button>
  </div>

  {#if !project.datasets.length}
    <div class="empty well">Import data first.</div>
  {:else if !current}
    <div class="empty well">Add a candidate model to fit, e.g. extended corresponding states.</div>
  {:else}
    <div class="tabs row">
      {#each project.candidates as c (c.id)}
        <button
          class="tab"
          class:on={c.id === current.id}
          onclick={() => (project.selected = { type: "candidate", id: c.id })}
        >
          {c.label}{c.fit ? "" : " *"}
        </button>
      {/each}
    </div>
    <div class="split">
      <fieldset class="group">
        <legend>Parameters of {current.label}</legend>
        <div class="well">
          <table class="grid">
            <thead>
              <tr><th>Parameter</th><th>Start</th><th>Free</th><th>Fitted ± s.e.</th><th>Unit</th></tr>
            </thead>
            <tbody>
              {#each Object.entries(current.start.parameters) as [name, p] (name)}
                <tr>
                  <td title={p.description}>{name}</td>
                  <td>
                    <input
                      class="field num start"
                      value={p.value}
                      onchange={(e) => setStart(name, (e.currentTarget as HTMLInputElement).value)}
                      aria-label="Start value of {name}"
                    />
                  </td>
                  <td>
                    <input
                      type="checkbox"
                      checked={!isFixed(name)}
                      onchange={(e) => setFixed(name, !(e.currentTarget as HTMLInputElement).checked)}
                      aria-label="Fit {name}"
                    />
                  </td>
                  <td class="num">
                    {#if current.fit && name in current.fit.summary.values}
                      {withError(current.fit.summary.values[name], current.fit.summary.standard_errors[name])}
                    {:else}
                      <span class="muted">{current.fit ? "fixed" : "–"}</span>
                    {/if}
                  </td>
                  <td>{p.unit === "1" ? "" : p.unit}</td>
                </tr>
              {/each}
            </tbody>
          </table>
        </div>
        <div class="opts">
          <label class="row"><input type="checkbox" bind:checked={project.settings.weighted} /> weight by stated uncertainty</label>
          <label class="row"><input type="checkbox" bind:checked={project.settings.scaleFactors} /> per-dataset scale factors</label>
          <label class="row">multistart <input class="field num small" type="number" min="0" max="50" bind:value={project.settings.multistart} /></label>
          <label class="row">seed <input class="field num small" type="number" min="0" bind:value={project.settings.seed} /></label>
        </div>
        <div class="row">
          <span class="muted">{freeParameters(current).length} free · {current.start.reference}</span>
          <span class="spacer"></span>
          <button class="btn" onclick={() => project.removeCandidate(current.id)}>Remove</button>
          <button class="btn default" onclick={() => project.fit(current.id)} disabled={!!project.busy}>
            {project.busy?.startsWith("Fit") ? "Fitting…" : "Fit"}
          </button>
        </div>
      </fieldset>

      <fieldset class="group">
        <legend>Fit</legend>
        {#if current.fit}
          {@const s = current.fit.summary}
          <table class="props">
            <tbody>
              <tr><td>AARD</td><td>{pct(s.deviations.aard, 3)} %</td></tr>
              <tr><td>Bias</td><td>{pct(s.deviations.bias, 3)} %</td></tr>
              <tr><td>RMS</td><td>{pct(s.deviations.rms, 3)} %</td></tr>
              <tr><td>Max |ARD|</td><td>{pct(s.deviations.max_abs, 3)} %</td></tr>
              <tr><td>Points</td><td>{s.deviations.n}</td></tr>
              <tr><td>AIC / BIC</td><td>{fmt(current.fit.criteria.aic)} / {fmt(current.fit.criteria.bic)}</td></tr>
              <tr><td>Evaluations</td><td>{s.nfev} ({s.starts} start{s.starts > 1 ? "s" : ""}, seed {s.seed})</td></tr>
              <tr><td>Converged</td><td class:ok={s.success} class:error={!s.success}>{s.success ? "yes" : s.message}</td></tr>
            </tbody>
          </table>
        {:else if current.error}
          <p class="error">{current.error}</p>
        {:else}
          <p class="muted">Not fitted yet.</p>
        {/if}
      </fieldset>
    </div>

    {#if current.fit}
      <div class="well plotbox">
        <ScatterPlot
          series={deviationSeries(current.fit)}
          xLabel="Temperature (K)"
          yLabel="100 (exp − model) / model (%)"
          zeroLine
          {band}
          bandLabel="median expanded uncertainty"
          height={250}
        />
      </div>
    {/if}
  {/if}
</div>

<style>
  .view {
    display: flex;
    flex-direction: column;
    gap: 6px;
    height: 100%;
    min-height: 0;
    overflow: auto;
  }
  .bar {
    flex-wrap: wrap;
  }
  .tabs {
    gap: 2px;
    border-bottom: 1px solid var(--shadow);
  }
  .tab {
    padding: 2px 10px;
    background: var(--face);
    border: 1px solid;
    border-color: var(--hilite) var(--dark) transparent var(--hilite);
  }
  .tab.on {
    font-weight: 700;
    background: var(--field);
  }
  .split {
    display: grid;
    grid-template-columns: minmax(0, 3fr) minmax(0, 2fr);
    gap: 8px;
  }
  .split fieldset {
    display: grid;
    gap: 6px;
    align-content: start;
  }
  .opts {
    display: flex;
    flex-wrap: wrap;
    gap: 4px 14px;
  }
  .start {
    width: 110px;
  }
  .small {
    width: 56px;
  }
  .ref {
    width: 80px;
  }
  .plotbox {
    padding: 4px;
  }
</style>
