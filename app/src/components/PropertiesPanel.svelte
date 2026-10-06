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
    {#if project.view === "worksheet" && dataset}
      {@const masked = new Set(project.masks[dataset.name] ?? [])}
      {@const vals = dataset.values.filter((_, i) => !masked.has(dataset.point_ids[i])).map((v) => v * display(dataset.quantity).factor)}
      <fieldset class="group">
        <legend>Worksheet: {dataset.name}</legend>
        <table class="props">
          <tbody>
            <tr><td>Source</td><td>{dataset.provenance?.doi ?? dataset.provenance?.citation ?? "–"}</td></tr>
            <tr><td>Uncertainty type</td><td>expanded, k = {dataset.coverage_factor}</td></tr>
            <tr><td>State</td><td>{dataset.pressure ? "T, p" : "T, ρ"}{dataset.molar_density && dataset.pressure ? " (saturation)" : ""}</td></tr>
          </tbody>
        </table>
      </fieldset>
      <fieldset class="group">
        <legend>Column statistics: {display(dataset.quantity).symbol}</legend>
        <table class="props">
          <tbody>
            <tr><td>N (unmasked)</td><td>{vals.length}</td></tr>
            <tr><td>Mean</td><td>{vals.length ? fmt(vals.reduce((a, b) => a + b, 0) / vals.length) : "–"} {display(dataset.quantity).unit}</td></tr>
            <tr><td>Min / max</td><td>{vals.length ? `${fmt(Math.min(...vals))} / ${fmt(Math.max(...vals))}` : "–"}</td></tr>
            <tr><td>Masked rows</td><td class:warn={masked.size > 0}>{masked.size}</td></tr>
          </tbody>
        </table>
      </fieldset>
      {#if dataset.provenance?.citation || dataset.provenance?.doi}
        <fieldset class="group">
          <legend>Reference</legend>
          <p class="why">{dataset.provenance?.citation ?? ""}{dataset.provenance?.doi ? ` doi:${dataset.provenance.doi}` : ""}</p>
          <div class="row actions">
            <button
              class="btn"
              onclick={() =>
                navigator.clipboard?.writeText(
                  `@misc{${dataset.name},\n  title = {${dataset.provenance?.citation ?? dataset.name}},\n  doi = {${dataset.provenance?.doi ?? ""}}\n}`,
                )}
            >Copy BibTeX</button>
            <button class="btn" onclick={() => navigator.clipboard?.writeText(dataset.provenance?.doi ?? "")} disabled={!dataset.provenance?.doi}>Copy DOI</button>
          </div>
        </fieldset>
      {/if}
    {:else if dataset}
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
    {:else if project.view === "consistency" && project.consistency}
      {@const report = project.consistency}
      <fieldset class="group">
        <legend>Study</legend>
        <table class="props">
          <tbody>
            <tr><td>Type</td><td>Data consistency</td></tr>
            <tr><td>Datasets</td><td>{project.datasets.length}</td></tr>
            {#each report.overlaps as o (o.a + o.b)}
              <tr><td>Overlap {o.a} / {o.b}</td><td>{fmt(o.t_range[0])}–{fmt(o.t_range[1])} K</td></tr>
            {/each}
            <tr><td>Models compared</td><td>{report.models.join(", ") || "none"}</td></tr>
          </tbody>
        </table>
      </fieldset>
      <fieldset class="group">
        <legend>Datasets (stated U)</legend>
        <table class="props">
          <tbody>
            {#each project.datasets as d (d.name)}
              <tr><td>{d.name}</td><td>{relU(d.values, d.expanded_uncertainty)}</td></tr>
            {/each}
          </tbody>
        </table>
      </fieldset>
      {#if report.offsets.some((o) => !report.models.includes(o.reference))}
        <fieldset class="group">
          <legend>Offsets between datasets</legend>
          <table class="props">
            <tbody>
              {#each report.offsets.filter((o) => !report.models.includes(o.reference)) as o (o.dataset + o.reference)}
                <tr>
                  <td>{o.dataset} vs {o.reference}</td>
                  <td class:warn={o.significant}>
                    {o.offset >= 0 ? "+" : ""}{o.offset.toFixed(1)} % ({o.ci95_total[0].toFixed(1)} to {o.ci95_total[1].toFixed(1)})
                  </td>
                </tr>
              {/each}
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
