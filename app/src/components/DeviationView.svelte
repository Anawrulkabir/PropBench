<script lang="ts">
  // Deviation plot (design/mockups/01_Main): fitted, held-out (cross-validation) or reference-model deviations
  // against temperature with the stated-uncertainty band, and the points behind the plot.
  import type { Series } from "../lib/plot";
  import { project } from "../lib/project.svelte";
  import { display, fmt, pct } from "../lib/quantities";
  import { pointSeries, typicalUncertainty } from "../lib/study";
  import ScatterPlot from "./ScatterPlot.svelte";

  interface Source {
    id: string;
    label: string;
    names: string[];
    pointIds: number[];
    ard: (number | null)[];
  }

  let choice = $state("");

  const candidate = $derived(
    (project.selected?.type === "candidate" ? project.candidate(project.selected.id) : undefined) ??
      project.candidates.find((c) => c.label === project.selection?.chosen) ??
      project.candidates.find((c) => c.fit),
  );

  const sources = $derived.by<Source[]>(() => {
    const out: Source[] = [];
    for (const c of project.candidates) {
      if (c.fit) {
        out.push({ id: `fit:${c.id}`, label: `Fit · ${c.label}`, names: c.fit.points.dataset, pointIds: c.fit.points.point_id, ard: c.fit.points.ard });
      }
      for (const [method, cv] of Object.entries(c.study?.cross_validation ?? {})) {
        if (cv.points) {
          out.push({ id: `${method}:${c.id}`, label: `${method.toUpperCase()} (held out) · ${c.label}`, names: cv.points.dataset, pointIds: cv.points.point_id, ard: cv.points.ard });
        }
      }
    }
    for (const row of project.comparison?.rows ?? []) {
      if (row.dataset === "all" || !row.point_ids || !row.ard) continue;
      const id = `ref:${row.model}`;
      const existing = out.find((s) => s.id === id);
      const names = row.point_ids.map(() => row.dataset);
      if (existing) {
        existing.names.push(...names);
        existing.pointIds.push(...row.point_ids);
        existing.ard.push(...row.ard);
      } else {
        out.push({ id, label: `Model · ${row.model}`, names: [...names], pointIds: [...row.point_ids], ard: [...row.ard] });
      }
    }
    return out;
  });

  const preferred = $derived(
    candidate
      ? (sources.find((s) => s.id === `${project.rule.validation}:${candidate.id}`) ?? sources.find((s) => s.id === `fit:${candidate.id}`))
      : sources[0],
  );
  const source = $derived(sources.find((s) => s.id === choice) ?? preferred);
  const series = $derived<Series[]>(source ? pointSeries(project.datasets, source.names, source.pointIds, source.ard) : []);
  const u = $derived(typicalUncertainty(project.activeDatasets()));
  const quantity = $derived(project.datasets[0]?.quantity ?? "viscosity");
  const unit = $derived(display(quantity));

  const table = $derived.by(() => {
    if (!source) return [];
    const byName = new Map(project.datasets.map((d) => [d.name, d]));
    return source.names.map((name, i) => {
      const d = byName.get(name);
      const k = d ? d.point_ids.indexOf(source.pointIds[i]) : -1;
      return {
        key: `${name}:${source.pointIds[i]}`,
        name,
        id: source.pointIds[i],
        t: d && k >= 0 ? d.temperature[k] : null,
        p: d && k >= 0 ? (d.pressure?.[k] ?? null) : null,
        phase: d && k >= 0 ? (d.phase?.[k] ?? "") : "",
        value: d && k >= 0 ? d.values[k] : null,
        u: d && k >= 0 && d.expanded_uncertainty ? (100 * d.expanded_uncertainty[k]) / d.values[k] : null,
        ard: source.ard[i],
      };
    });
  });
</script>

<div class="view">
  <div class="bar row">
    <span>100 ({unit.symbol} exp − {unit.symbol} model) / {unit.symbol} model, %</span>
    <span class="spacer"></span>
    <label class="row">Plot
      <select class="field wide" value={source?.id ?? ""} onchange={(e) => (choice = (e.currentTarget as HTMLSelectElement).value)}>
        {#each sources as s (s.id)}<option value={s.id}>{s.label}</option>{/each}
      </select>
    </label>
    <button class="btn" onclick={() => project.compareModels()} disabled={!!project.busy || !project.datasets.length}>Add reference models</button>
  </div>

  {#if !sources.length}
    <div class="empty well">
      Fit a model (Models tab), run a study, or compare with the reference models to see deviation plots here.
    </div>
  {:else}
    <div class="well plotbox">
      <ScatterPlot
        {series}
        xLabel="Temperature (K)"
        yLabel="deviation (%)"
        zeroLine
        band={u === null ? null : [-u, u]}
        bandLabel="median expanded uncertainty"
        height={260}
      />
    </div>
    <div class="well tablebox">
      <table class="grid">
        <thead>
          <tr><th>Dataset</th><th>#</th><th>T (K)</th><th>p (MPa)</th><th>Phase</th><th>{unit.symbol} exp ({unit.unit})</th><th>U (%)</th><th>Deviation (%)</th></tr>
        </thead>
        <tbody>
          {#each table as r (r.key)}
            <tr>
              <td>{r.name}</td>
              <td class="num">{r.id + 1}</td>
              <td class="num">{fmt(r.t, 6)}</td>
              <td class="num">{r.p === null ? "" : fmt(r.p * 1e-6, 4)}</td>
              <td>{r.phase}</td>
              <td class="num">{r.value === null ? "" : fmt(r.value * unit.factor, 5)}</td>
              <td class="num">{r.u === null ? "" : r.u.toFixed(2)}</td>
              <td class="num" class:error={r.u !== null && r.ard !== null && Math.abs(r.ard) > r.u}>{pct(r.ard, 2)}</td>
            </tr>
          {/each}
        </tbody>
      </table>
    </div>
  {/if}
</div>

<style>
  .view {
    display: flex;
    flex-direction: column;
    gap: 6px;
    height: 100%;
    min-height: 0;
  }
  .wide {
    min-width: 300px;
  }
  .plotbox {
    padding: 4px;
  }
  .tablebox {
    flex: 1;
    min-height: 80px;
    overflow: auto;
  }
</style>
