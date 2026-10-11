<script lang="ts">
  // Data consistency (design/mockups/02_Consistency): overlaps, model-free checks at equal T, offsets, z-scores.
  import { offsetText, pairChecks, plotLabel } from "../lib/consistency";
  import type { Line, Series } from "../lib/plot";
  import { project } from "../lib/project.svelte";
  import { display, pct } from "../lib/quantities";
  import ScatterPlot from "./ScatterPlot.svelte";

  let plotIndex = $state(0);

  const report = $derived(project.consistency);
  const quantity = $derived(project.datasets[0]?.quantity ?? "viscosity");
  const unit = $derived(display(quantity));
  const plot = $derived(report?.plots[Math.min(plotIndex, (report?.plots.length ?? 1) - 1)]);

  const series = $derived<Series[]>(
    plot
      ? plot.points.map((pts, i) => ({
          name: pts.dataset + (pts.expanded_uncertainty ? " with U" : ""),
          x: pts.pressure.map((p) => p * 1e-6),
          y: pts.value.map((v) => v * unit.factor),
          err: pts.expanded_uncertainty?.map((u) => u * unit.factor),
          shape: i === 0 ? "square" : "circle",
          open: i === 1,
        }))
      : [],
  );
  const lines = $derived<Line[]>(
    plot
      ? [
          {
            name: `pressure trend of ${plot.reference}`,
            x: plot.trend.pressure.map((p) => p * 1e-6),
            y: plot.trend.value.map((v) => v * unit.factor),
            color: "#1f5fa8",
            dashed: true,
          },
        ]
      : [],
  );
  const checks = $derived(report && plot ? pairChecks(report, plot.reference, plot.other) : []);
</script>

<div class="view">
  <div class="bar row">
    <b>Data consistency</b>
    {#if report}<span class="muted">· {report.overlaps.length} overlaps · {report.warnings.length} warnings</span>{/if}
    <span class="spacer"></span>
    <label class="row">isotherm tolerance (K)
      <input class="field num small" type="number" min="0" step="0.1" bind:value={project.consistencySettings.tTol} />
    </label>
    <label class="row"><input type="checkbox" bind:checked={project.consistencySettings.references} /> reference models</label>
    <button class="btn default" onclick={() => project.analyzeConsistency()} disabled={!!project.busy || !project.datasets.length}>
      {project.busy === "Consistency" ? "Checking…" : "Check consistency"}
    </button>
  </div>

  {#if !project.datasets.length}
    <div class="empty well">Import data first.</div>
  {:else if !report}
    <div class="empty well">
      Finds overlaps between datasets, compares them without a model (pressure trend at equal temperature), and
      estimates each dataset's offset with its uncertainty — against the other datasets, the reference models and
      any fitted models.
    </div>
  {:else}
    {#if report.plots.length}
      <div class="row">
        <label class="row">Plot
          <select class="field wide" bind:value={plotIndex}>
            {#each report.plots as p, i (i)}<option value={i}>{plotLabel(p)}</option>{/each}
          </select>
        </label>
      </div>
      <div class="well plotbox">
        <ScatterPlot {series} {lines} xLabel="Pressure (MPa)" yLabel="{unit.symbol} ({unit.unit}) at {plot?.temperature.toFixed(2)} K" height={250} />
      </div>
      <div class="well">
        <table class="grid">
          <thead><tr><th style="width: 24px"></th><th>Check</th><th>Result</th></tr></thead>
          <tbody>
            {#each checks as c (c.check)}
              <tr>
                <td class:ok={c.ok === true} class:warn={c.ok === null} class:error={c.ok === false}>
                  {c.ok === true ? "✓" : c.ok === null ? "·" : "✗"}
                </td>
                <td>{c.check}</td>
                <td class="mono">{c.result}</td>
              </tr>
            {/each}
          </tbody>
        </table>
      </div>
    {:else}
      <div class="notice">
        No isotherm is shared by two datasets{report.overlaps.length ? " within the tolerance" : ""}: only
        model-based offsets are available.
      </div>
    {/if}

    <fieldset class="group">
      <legend>Offsets (constant relative offset, 95 % intervals)</legend>
      <div class="well">
        <table class="grid">
          <thead>
            <tr><th>Dataset</th><th>Against</th><th>n</th><th>Offset</th><th>95 % (statistical)</th><th>95 % (with reference U)</th><th>Birge</th><th>Extrap.</th></tr>
          </thead>
          <tbody>
            {#each report.offsets as o (o.dataset + o.reference)}
              <tr class:sig={o.significant}>
                <td>{o.dataset}</td>
                <td>{o.reference}</td>
                <td class="num">{o.n}</td>
                <td class="num">{offsetText(o)}</td>
                <td class="num">{o.ci95[0].toFixed(2)} … {o.ci95[1].toFixed(2)}</td>
                <td class="num">{o.ci95_total[0].toFixed(2)} … {o.ci95_total[1].toFixed(2)}</td>
                <td class="num">{o.birge === null ? "–" : o.birge.toFixed(2)}</td>
                <td class="num">{o.extrapolated || ""}</td>
              </tr>
            {/each}
          </tbody>
        </table>
      </div>
      <p class="muted">
        Bold: the interval including the reference's stated uncertainty excludes zero. Birge ratio &gt; 1: scatter
        larger than the stated uncertainties (interval widened).
      </p>
    </fieldset>

    {#if report.z_scores.length}
      <fieldset class="group">
        <legend>z-scores against stated uncertainties</legend>
        <table class="grid">
          <thead><tr><th>Dataset</th><th>Model</th><th>|z| &gt; 2</th><th>max |z|</th></tr></thead>
          <tbody>
            {#each report.z_scores as z (z.dataset + z.reference)}
              <tr>
                <td>{z.dataset}</td>
                <td>{z.reference}</td>
                <td class="num" class:error={z.n_outside > 0}>{z.n_outside} of {z.z.length}</td>
                <td class="num">{pct(z.max_abs, 1)}</td>
              </tr>
            {/each}
          </tbody>
        </table>
      </fieldset>
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
  .small {
    width: 52px;
  }
  .wide {
    min-width: 360px;
  }
  .plotbox {
    padding: 4px;
  }
  tr.sig td {
    font-weight: 700;
  }
</style>
