<script lang="ts">
  import { worker } from "../lib/api";
  import type { Line, Series } from "../lib/plot";
  import { project } from "../lib/project.svelte";
  import { display, fmt } from "../lib/quantities";
  import { commonTarget } from "../lib/study";
  import ScatterPlot from "./ScatterPlot.svelte";

  let plot = $state<"pT" | "values">("pT");
  let saturation = $state<Line | null>(null);
  let satKey = "";

  const target = $derived(commonTarget(project.datasets));
  const fluid = $derived(typeof target === "string" ? null : target.fluid);
  const quantity = $derived(typeof target === "string" ? (project.datasets[0]?.quantity ?? "") : target.quantity);
  const unit = $derived(display(quantity));
  const total = $derived(project.datasets.reduce((n, d) => n + d.values.length, 0));

  const pT = $derived<Series[]>(
    project.datasets
      .filter((d) => d.pressure)
      .map((d) => ({ name: d.name, x: d.temperature, y: (d.pressure ?? []).map((p) => p * 1e-6) })),
  );
  const values = $derived<Series[]>(
    project.datasets.map((d) => ({ name: d.name, x: d.temperature, y: d.values.map((v) => v * unit.factor) })),
  );

  // saturation curve of the reference equation of state, computed by the worker
  $effect(() => {
    const ts = project.datasets.flatMap((d) => d.temperature);
    if (!fluid || ts.length === 0) {
      saturation = null;
      return;
    }
    const lo = Math.min(...ts) * 0.9;
    const key = `${fluid}:${lo}`;
    if (key === satKey) return;
    satKey = key;
    worker<{ outputs: Record<string, (number | null)[]> }>("properties", {
      fluid,
      pair: "PT_INPUTS",
      values1: [1e5],
      values2: [300],
      outputs: ["T_critical"],
    })
      .then(async (crit) => {
        const tc = crit.outputs.T_critical[0];
        if (tc === null) return;
        const n = 40;
        const t = Array.from({ length: n }, (_, i) => lo + ((tc - lo) * i) / (n - 1)).filter((x) => x < tc);
        const sat = await worker<{ outputs: Record<string, (number | null)[]> }>("properties", {
          fluid,
          pair: "QT_INPUTS",
          values1: t.map(() => 0),
          values2: t,
          outputs: ["P"],
        });
        saturation = {
          name: "Saturation curve (reference EoS)",
          x: t,
          y: sat.outputs.P.map((p) => (p === null ? null : p * 1e-6)),
          color: "#333",
        };
      })
      .catch(() => (saturation = null));
  });

  interface Row {
    ok: boolean | null;
    check: string;
    result: string;
  }
  const rows = $derived.by<Row[]>(() => {
    const checks = Object.values(project.checks);
    const mismatches = checks.reduce((n, c) => n + c.phase_mismatches.length, 0);
    const outside = checks.reduce((n, c) => n + Object.keys(c.errors).length, 0);
    const withU = project.datasets.reduce((n, d) => n + (d.expanded_uncertainty ? d.values.length : 0), 0);
    const out: Row[] = [
      { ok: true, check: "Rows imported", result: `${total} in ${project.datasets.length} datasets` },
      { ok: true, check: "Units converted to SI", result: "all columns" },
      {
        ok: typeof target !== "string",
        check: "One fluid and one property",
        result: typeof target === "string" ? target : `${target.fluid}, ${display(target.quantity).label}`,
      },
      { ok: mismatches === 0, check: "Phase from file vs equation of state", result: `${mismatches} disagree` },
      { ok: outside === 0, check: "Points outside the EoS range", result: String(outside) },
      { ok: withU === total ? true : null, check: "Stated uncertainty present", result: `${withU} of ${total}` },
    ];
    // overlapping datasets in temperature (worth a consistency look)
    const ranges = project.datasets.map((d) => [Math.min(...d.temperature), Math.max(...d.temperature)]);
    let overlaps = 0;
    for (let i = 0; i < ranges.length; i++)
      for (let j = i + 1; j < ranges.length; j++)
        if (ranges[i][0] <= ranges[j][1] && ranges[j][0] <= ranges[i][1]) overlaps++;
    out.push({ ok: overlaps === 0 ? true : null, check: "Datasets overlapping in T", result: String(overlaps) });
    return out;
  });
</script>

<div class="view">
  <div class="bar row">
    <b>Data check</b>
    <span class="muted">· {project.datasets.length} datasets · {total} points</span>
    <span class="spacer"></span>
    <label class="row">Plot
      <select class="field" bind:value={plot}>
        <option value="pT">p against T</option>
        <option value="values">{unit.label} against T</option>
      </select>
    </label>
    <button class="btn" onclick={() => project.checkData()} disabled={!!project.busy || !project.datasets.length}>Check again</button>
    <button class="btn" onclick={() => (project.view = "fit")} disabled={!project.datasets.length}>Continue to models</button>
  </div>

  {#if project.datasets.length === 0}
    <div class="empty well">
      <p>No data yet.</p>
      <button class="btn default" onclick={() => (project.importOpen = true)}>Import data…</button>
    </div>
  {:else}
    <div class="well plotbox">
      {#if plot === "pT" && pT.length}
        <ScatterPlot series={pT} lines={saturation ? [saturation] : []} xLabel="Temperature (K)" yLabel="p (MPa)" height={250} />
      {:else}
        <ScatterPlot series={values} xLabel="Temperature (K)" yLabel="{unit.symbol} ({unit.unit})" height={250} />
      {/if}
    </div>
    <div class="well tablebox">
      <table class="grid">
        <thead><tr><th style="width: 24px"></th><th>Check</th><th>Result</th></tr></thead>
        <tbody>
          {#each rows as r (r.check)}
            <tr>
              <td class:ok={r.ok === true} class:warn={r.ok === null} class:error={r.ok === false}>
                {r.ok === true ? "✓" : r.ok === null ? "⚠" : "✗"}
              </td>
              <td>{r.check}</td>
              <td class="mono">{r.result}</td>
            </tr>
          {/each}
        </tbody>
      </table>
    </div>
    <div class="well tablebox">
      <table class="grid">
        <thead>
          <tr><th>Dataset</th><th>Points</th><th>T (K)</th><th>p (MPa)</th><th>{unit.symbol} ({unit.unit})</th><th>Phases (EoS)</th></tr>
        </thead>
        <tbody>
          {#each project.datasets as d (d.name)}
            {@const c = project.checks[d.name]}
            <tr
              class="clickable"
              class:sel={project.selected?.type === "dataset" && project.selected.name === d.name}
              onclick={() => (project.selected = { type: "dataset", name: d.name })}
            >
              <td>{d.name}</td>
              <td class="num">{d.values.length}</td>
              <td class="num">{fmt(Math.min(...d.temperature))} – {fmt(Math.max(...d.temperature))}</td>
              <td class="num">
                {d.pressure ? `${fmt(Math.min(...d.pressure) * 1e-6)} – ${fmt(Math.max(...d.pressure) * 1e-6)}` : "–"}
              </td>
              <td class="num">{fmt(Math.min(...d.values) * unit.factor)} – {fmt(Math.max(...d.values) * unit.factor)}</td>
              <td>{c ? Object.entries(c.phases).map(([k, v]) => `${k} ${v}`).join(", ") : "…"}</td>
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
    overflow: auto;
  }
  .bar {
    flex-wrap: wrap;
  }
  .plotbox {
    padding: 4px;
  }
  .tablebox {
    flex-shrink: 0;
  }
</style>
