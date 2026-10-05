<script lang="ts">
  import { project } from "../lib/project.svelte";
  import { display, fmt, pct, withError } from "../lib/quantities";
  import { freeParameters, physicsPassed } from "../lib/study";

  const dataset = $derived(
    project.selected?.type === "dataset"
      ? project.datasets.find((d) => project.selected?.type === "dataset" && d.name === project.selected.name)
      : undefined,
  );
  const check = $derived(dataset ? project.checks[dataset.name] : undefined);
  const candidate = $derived(project.selected?.type === "candidate" ? project.candidate(project.selected.id) : undefined);
  const chosen = $derived(project.candidates.find((c) => c.label === project.selection?.chosen));

  function range(values: number[] | null, factor = 1, digits = 4): string {
    if (!values || values.length === 0) return "–";
    return `${fmt(Math.min(...values) * factor, digits)} – ${fmt(Math.max(...values) * factor, digits)}`;
  }
  function relU(values: number[], u: number[] | null): string {
    if (!u) return "not stated";
    const rel = u.map((x, i) => (100 * x) / Math.abs(values[i]));
    return `${pct(Math.min(...rel))} – ${pct(Math.max(...rel))} %`;
  }
</script>

<aside class="props-panel">
  <header class="titlebar">Properties</header>
  <div class="body">
    {#if dataset}
      <fieldset class="group">
        <legend>Dataset: {dataset.name}</legend>
        <table class="props">
          <tbody>
            <tr><td>Fluid</td><td>{dataset.fluid}</td></tr>
            <tr><td>Property</td><td>{display(dataset.quantity).label}</td></tr>
            <tr><td>Points</td><td>{dataset.values.length}</td></tr>
            <tr><td>T range</td><td>{range(dataset.temperature)} K</td></tr>
            {#if dataset.pressure}<tr><td>p range</td><td>{range(dataset.pressure, 1e-6)} MPa</td></tr>{/if}
            <tr>
              <td>Values</td>
              <td>{range(dataset.values, display(dataset.quantity).factor)} {display(dataset.quantity).unit}</td>
            </tr>
            <tr><td>Stated U (k={dataset.coverage_factor})</td><td>{relU(dataset.values, dataset.expanded_uncertainty)}</td></tr>
            {#if check}
              <tr>
                <td>Phases (EoS)</td>
                <td>{Object.entries(check.phases).map(([k, v]) => `${k} ${v}`).join(", ") || "–"}</td>
              </tr>
            {/if}
            {#if dataset.provenance?.doi}<tr><td>DOI</td><td>{dataset.provenance.doi}</td></tr>{/if}
            {#if dataset.provenance?.citation}<tr><td>Source</td><td>{dataset.provenance.citation}</td></tr>{/if}
            {#if dataset.provenance?.method}<tr><td>Method</td><td>{dataset.provenance.method}</td></tr>{/if}
          </tbody>
        </table>
        <div class="row actions">
          <span class="spacer"></span>
          <button class="btn" onclick={() => dataset && project.removeDataset(dataset.name)}>Remove</button>
        </div>
      </fieldset>
    {:else if candidate}
      <fieldset class="group">
        <legend>Model</legend>
        <table class="props">
          <tbody>
            <tr><td>Name</td><td>{candidate.label}</td></tr>
            <tr><td>Kind</td><td>{candidate.start.name}</td></tr>
            {#if candidate.start.reference_fluid}<tr><td>Reference fluid</td><td>{candidate.start.reference_fluid}</td></tr>{/if}
            <tr><td>Free parameters</td><td>{freeParameters(candidate).join(", ") || "none"}</td></tr>
            <tr><td>Source</td><td>{candidate.start.reference}</td></tr>
          </tbody>
        </table>
      </fieldset>
      {#if candidate.fit}
        <fieldset class="group">
          <legend>Parameters (± standard error)</legend>
          <table class="props">
            <tbody>
              {#each Object.entries(candidate.fit.summary.values) as [name, value] (name)}
                <tr><td>{name}</td><td>{withError(value, candidate.fit.summary.standard_errors[name])}</td></tr>
              {/each}
              {#each Object.entries(candidate.fit.summary.scale_factors) as [name, value] (name)}
                <tr><td>scale · {name}</td><td>{fmt(value, 6)}</td></tr>
              {/each}
            </tbody>
          </table>
        </fieldset>
      {/if}
      {#if candidate.study}
        <fieldset class="group">
          <legend>Validation</legend>
          <table class="props">
            <tbody>
              {#each Object.entries(candidate.study.cross_validation) as [method, cv] (method)}
                <tr><td>{method.toUpperCase()} AARD</td><td>{pct(cv.pooled.aard)} %</td></tr>
              {/each}
              <tr>
                <td>Physics checks</td>
                <td class:ok={physicsPassed(candidate.study) === true} class:error={physicsPassed(candidate.study) === false}>
                  {physicsPassed(candidate.study) ? "all passed" : "violations"}
                </td>
              </tr>
            </tbody>
          </table>
        </fieldset>
      {/if}
    {:else if chosen && project.selection}
      <fieldset class="group">
        <legend>Why this model</legend>
        <p class="why">{project.selection.reason}</p>
      </fieldset>
    {:else}
      <p class="muted pad">Select a dataset or a model in the project tree.</p>
    {/if}
  </div>
</aside>

<style>
  .props-panel {
    display: flex;
    flex-direction: column;
    height: 100%;
    min-height: 0;
  }
  .titlebar {
    padding: 2px 6px;
    font-weight: 700;
    color: #0a1a3a;
    background: var(--panel-title);
  }
  .body {
    display: grid;
    gap: 8px;
    align-content: start;
    padding: 6px;
    overflow: auto;
  }
  .actions {
    margin-top: 6px;
  }
  .why {
    margin: 2px 0;
    line-height: 1.4;
  }
  .pad {
    padding: 8px;
  }
</style>
