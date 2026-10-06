<script lang="ts">
  // Graph studio (design/mockups/09_GraphStudio): object manager, plot types, plot details and publication export.
  // Data and model curves come from the worker; the UI only arranges and draws them (one plot per figure, legend
  // inside the axes, journal presets; CLAUDE.md figure conventions).
  import { errorMessage, worker } from "../lib/api";
  import type { Line, Series } from "../lib/plot";
  import { breakAtPhaseChange, SERIES_COLORS } from "../lib/plot";
  import { project } from "../lib/project.svelte";
  import { display } from "../lib/quantities";
  import { deviationSeries, pointSeries } from "../lib/study";
  import type { ModelSpec } from "../lib/types";
  import Icon from "./Icon.svelte";
  import ScatterPlot from "./ScatterPlot.svelte";

  type Kind = "property" | "errorbars" | "deviation" | "parity" | "pt";
  const TYPES: { id: Kind | string; label: string; icon: string; enabled: boolean }[] = [
    { id: "property", label: "Line + symbol", icon: "chart", enabled: true },
    { id: "errorbars", label: "Error bars", icon: "chart", enabled: true },
    { id: "deviation", label: "Deviation", icon: "fit", enabled: true },
    { id: "parity", label: "Parity", icon: "fit", enabled: true },
    { id: "pt", label: "p–T diagram", icon: "chart", enabled: true },
    ...["Column", "Box", "Histogram", "Contour", "Heat map", "3D surface", "Ternary", "Polar", "p–h diagram", "T–s diagram", "Residual Q–Q"].map(
      (label) => ({ id: label, label, icon: "results", enabled: false }),
    ),
  ];
  const PRESETS = [
    { id: "elsevier1", label: "Elsevier, 1 column (90 mm)", mm: 90 },
    { id: "elsevier2", label: "Elsevier, 2 columns (190 mm)", mm: 190 },
    { id: "acs1", label: "ACS, 1 column (3.25 in)", mm: 82.55 },
    { id: "springer1", label: "Springer, 1 column (84 mm)", mm: 84 },
  ];

  let kind = $state<Kind>("property");
  let modelKey = $state("");
  let isobarsText = $state("2, 3, 4");
  let curves = $state<Line[]>([]);
  let hidden = $state<Record<string, boolean>>({});
  let title = $state("");
  let xFrom = $state("");
  let xTo = $state("");
  let yFrom = $state("");
  let yTo = $state("");
  let markerSize = $state(4);
  let errorBars = $state(true);
  let legend = $state(true);
  let preset = $state("elsevier1");
  let format = $state<"svg" | "png">("svg");
  let dpi = $state(600);
  let references = $state<{ label: string; model: ModelSpec }[]>([]);
  let busy = $state(false);
  let error = $state<string | null>(null);
  let canvas: HTMLDivElement | undefined = $state();

  const quantity = $derived(project.datasets[0]?.quantity ?? "viscosity");
  const unit = $derived(display(quantity));
  const fluid = $derived(project.datasets[0]?.fluid ?? "");
  const models = $derived([
    ...project.candidates.filter((c) => c.fit).map((c) => ({ key: `c:${c.id}`, label: c.label, spec: c.fit?.model as ModelSpec })),
    ...references.map((r) => ({ key: `r:${r.label}`, label: r.label, spec: r.model })),
  ]);
  const model = $derived(models.find((m) => m.key === modelKey) ?? models[0]);

  $effect(() => {
    if (!fluid) return;
    worker<{ references: { label: string; model: ModelSpec }[] }>("model.references", { fluid, quantity })
      .then((r) => (references = r.references))
      .catch(() => (references = []));
  });

  async function computeCurves() {
    if (!model || !project.datasets.length) return;
    error = null;
    busy = true;
    try {
      const ts = project.datasets.flatMap((d) => d.temperature);
      const lo = Math.min(...ts) - 5;
      const hi = Math.max(...ts) + 5;
      const grid = Array.from({ length: 60 }, (_, i) => lo + ((hi - lo) * i) / 59);
      const pressures = isobarsText.split(/[,;\s]+/).map(Number).filter((p) => Number.isFinite(p) && p > 0);
      const out: Line[] = [];
      for (const [i, p] of pressures.entries()) {
        const r = await worker<{ values: (number | null)[] }>("model.predict", {
          model: model.spec,
          temperature: grid,
          pressure: grid.map(() => p * 1e6),
        });
        out.push({ name: `${model.label}, ${p} MPa`, x: grid, y: breakAtPhaseChange(r.values.map((v) => (v === null ? null : v * unit.factor))), color: SERIES_COLORS[(i + 3) % SERIES_COLORS.length] });
      }
      curves = out;
      project.note(`Graph studio: ${out.length} isobars of ${model.label}`);
    } catch (err) {
      error = errorMessage(err);
    } finally {
      busy = false;
    }
  }

  const data = $derived.by<{ series: Series[]; lines: Line[]; x: string; y: string; band: [number, number] | null; zero: boolean }>(() => {
    const ds = project.activeDatasets();
    if (kind === "pt") {
      return {
        series: ds.filter((d) => d.pressure).map((d) => ({ name: d.name, x: d.temperature, y: (d.pressure ?? []).map((p) => p * 1e-6) })),
        lines: [], x: "Temperature, T / K", y: "Pressure, p / MPa", band: null, zero: false,
      };
    }
    const fitted = project.candidates.find((c) => c.label === model?.label)?.fit;
    if (kind === "deviation") {
      const row = project.comparison?.rows.filter((r) => r.model === model?.label && r.point_ids);
      const series = fitted
        ? deviationSeries(fitted)
        : row?.length
          ? pointSeries(project.datasets, row.flatMap((r) => r.point_ids?.map(() => r.dataset) ?? []), row.flatMap((r) => r.point_ids ?? []), row.flatMap((r) => r.ard ?? []))
          : [];
      return { series, lines: [], x: "Temperature, T / K", y: `100 (${unit.symbol}exp − ${unit.symbol}model)/${unit.symbol}model`, band: null, zero: true };
    }
    if (kind === "parity" && fitted) {
      const groups = new Map<string, Series>();
      fitted.points.dataset.forEach((name, i) => {
        const a = fitted.points.ard[i];
        if (a === null) return;
        const exp = fitted.points.value[i] * unit.factor;
        const g = groups.get(name) ?? { name, x: [], y: [] };
        g.x.push(exp / (1 + a / 100));
        g.y.push(exp);
        groups.set(name, g);
      });
      const all = [...groups.values()].flatMap((g) => g.x);
      const lim = all.length ? [Math.min(...all), Math.max(...all)] : [0, 1];
      return { series: [...groups.values()], lines: [{ name: "y = x", x: lim, y: lim, color: "#333", dashed: true }], x: `${unit.symbol} model / ${unit.unit}`, y: `${unit.symbol} exp / ${unit.unit}`, band: null, zero: false };
    }
    return {
      series: ds.map((d) => ({
        name: d.name,
        x: d.temperature,
        y: d.values.map((v) => v * unit.factor),
        err: kind === "errorbars" || errorBars ? d.expanded_uncertainty?.map((u) => u * unit.factor) : undefined,
      })),
      lines: curves,
      x: "Temperature, T / K",
      y: `${unit.symbol} / ${unit.unit}`,
      band: null,
      zero: false,
    };
  });

  const shownSeries = $derived(data.series.filter((s) => !hidden[s.name]));
  const shownLines = $derived(data.lines.filter((l) => !hidden[l.name]));
  const range = (a: string, b: string): [number, number] | null =>
    a.trim() !== "" && b.trim() !== "" && Number.isFinite(Number(a)) && Number.isFinite(Number(b)) ? [Number(a), Number(b)] : null;

  function svgText(): string | null {
    const svg = canvas?.querySelector("svg");
    if (!svg) return null;
    const clone = svg.cloneNode(true) as SVGSVGElement;
    const mm = PRESETS.find((p) => p.id === preset)?.mm ?? 90;
    const vb = svg.viewBox.baseVal;
    clone.setAttribute("width", `${mm}mm`);
    clone.setAttribute("height", `${(mm * vb.height) / vb.width}mm`);
    clone.setAttribute("style", "font-family: Arial, Helvetica, sans-serif; font-size: 10px; background: #fff");
    return new XMLSerializer().serializeToString(clone);
  }

  function download(blob: Blob, name: string) {
    const url = URL.createObjectURL(blob);
    const a = document.createElement("a");
    a.href = url;
    a.download = name;
    a.click();
    setTimeout(() => URL.revokeObjectURL(url), 1000);
  }

  async function exportFigure() {
    const text = svgText();
    if (!text) return;
    if (format === "svg") {
      download(new Blob([text], { type: "image/svg+xml" }), "propbench-figure.svg");
      project.note(`Figure exported as SVG (${PRESETS.find((p) => p.id === preset)?.label})`);
      return;
    }
    const svg = canvas?.querySelector("svg");
    if (!svg) return;
    const mm = PRESETS.find((p) => p.id === preset)?.mm ?? 90;
    const vb = svg.viewBox.baseVal;
    const width = Math.round((mm / 25.4) * dpi);
    const height = Math.round((width * vb.height) / vb.width);
    const img = new Image();
    img.onload = () => {
      const c = document.createElement("canvas");
      c.width = width;
      c.height = height;
      const ctx = c.getContext("2d");
      if (!ctx) return;
      ctx.fillStyle = "#fff";
      ctx.fillRect(0, 0, width, height);
      ctx.drawImage(img, 0, 0, width, height);
      c.toBlob((b) => b && download(b, "propbench-figure.png"), "image/png");
      project.note(`Figure exported as PNG, ${width} × ${height} px (${dpi} dpi)`);
    };
    img.src = "data:image/svg+xml;charset=utf-8," + encodeURIComponent(text);
  }
</script>

<div class="studio">
  <aside class="objects well">
    <div class="head">Object manager</div>
    <div class="node">▣ Graph1 ({PRESETS.find((p) => p.id === preset)?.mm} mm)</div>
    <div class="node sub">🗀 Layer 1: {TYPES.find((t) => t.id === kind)?.label}</div>
    {#each data.series as s (s.name)}
      <label class="leaf"><input type="checkbox" checked={!hidden[s.name]} onchange={() => (hidden[s.name] = !hidden[s.name])} /> ▦ {s.name}</label>
    {/each}
    {#each data.lines as l (l.name)}
      <label class="leaf"><input type="checkbox" checked={!hidden[l.name]} onchange={() => (hidden[l.name] = !hidden[l.name])} /> ƒ {l.name}</label>
    {/each}
    {#if !data.series.length && !data.lines.length}<div class="leaf muted">(empty — import data)</div>{/if}
  </aside>

  <div class="middle">
    <div class="types">
      {#each TYPES as t (t.id)}
        <button
          class="btn type"
          class:on={kind === t.id}
          disabled={!t.enabled}
          title={t.enabled ? t.label : `${t.label}: M3b`}
          onclick={() => t.enabled && (kind = t.id as Kind)}
        >
          <Icon name={t.icon} /><span>{t.label}</span>
        </button>
      {/each}
    </div>
    <div class="page" bind:this={canvas}>
      {#if project.datasets.length}
        <div class="paper">
          <ScatterPlot
            series={shownSeries}
            lines={shownLines}
            xLabel={data.x}
            yLabel={data.y}
            zeroLine={data.zero}
            height={400}
            xRange={range(xFrom, xTo)}
            yRange={range(yFrom, yTo)}
            {title}
            showLegend={legend}
            {markerSize}
          />
        </div>
      {:else}
        <div class="empty">Import data to start a graph.</div>
      {/if}
    </div>
  </div>

  <aside class="details">
    <fieldset class="group">
      <legend>Plot type</legend>
      <div class="form">
        <span>Type</span><span class="mono">{TYPES.find((t) => t.id === kind)?.label}</span>
        <label for="g-model">Model</label>
        <select id="g-model" class="field" value={model?.key ?? ""} onchange={(e) => (modelKey = (e.currentTarget as HTMLSelectElement).value)}>
          {#each models as m (m.key)}<option value={m.key}>{m.label}</option>{:else}<option value="">(fit a model or compare)</option>{/each}
        </select>
        <label for="g-iso">Isobars (MPa)</label>
        <input id="g-iso" class="field" bind:value={isobarsText} />
      </div>
      <div class="row end"><button class="btn" onclick={computeCurves} disabled={busy || !model}>{busy ? "Computing…" : "Add model isobars"}</button></div>
      {#if error}<p class="error">{error}</p>{/if}
    </fieldset>
    <fieldset class="group">
      <legend>Symbols, error bars and legend</legend>
      <div class="form">
        <label for="g-size">Symbol size</label>
        <input id="g-size" class="field num" type="number" min="1" max="10" bind:value={markerSize} />
      </div>
      <label class="row"><input type="checkbox" bind:checked={errorBars} /> Y error bars from stated U</label>
      <label class="row"><input type="checkbox" bind:checked={legend} /> Legend inside the axes</label>
    </fieldset>
    <fieldset class="group">
      <legend>Axes</legend>
      <div class="form">
        <label for="g-title">Title</label>
        <input id="g-title" class="field" bind:value={title} placeholder="(none)" />
        <span>X from / to</span>
        <span class="row"><input class="field num half" bind:value={xFrom} placeholder="auto" /><input class="field num half" bind:value={xTo} placeholder="auto" /></span>
        <span>Y from / to</span>
        <span class="row"><input class="field num half" bind:value={yFrom} placeholder="auto" /><input class="field num half" bind:value={yTo} placeholder="auto" /></span>
      </div>
    </fieldset>
    <fieldset class="group">
      <legend>Export</legend>
      <div class="form">
        <label for="g-fmt">Format</label>
        <select id="g-fmt" class="field" bind:value={format}><option value="svg">SVG (vector)</option><option value="png">PNG</option></select>
        <label for="g-dpi">Resolution</label>
        <select id="g-dpi" class="field" bind:value={dpi} disabled={format === "svg"}>
          {#each [300, 600, 1200, 2500] as d (d)}<option value={d}>{d} dpi</option>{/each}
        </select>
        <label for="g-preset">Preset</label>
        <select id="g-preset" class="field" bind:value={preset}>{#each PRESETS as p (p.id)}<option value={p.id}>{p.label}</option>{/each}</select>
      </div>
      <div class="row end">
        <button class="btn" disabled title="Templates: M3b">Save template…</button>
        <button class="btn default" onclick={exportFigure} disabled={!project.datasets.length}>Export</button>
      </div>
      <p class="muted">PDF export and matplotlib journal styles: M3b.</p>
    </fieldset>
  </aside>
</div>

<style>
  .studio {
    display: grid;
    grid-template-columns: 170px minmax(0, 1fr) 230px;
    gap: 6px;
    height: 100%;
    min-height: 0;
  }
  .objects {
    padding: 4px;
    overflow: auto;
  }
  .head {
    margin-bottom: 4px;
    font-weight: 700;
  }
  .node,
  .leaf {
    display: flex;
    align-items: center;
    gap: 4px;
    min-height: 18px;
    white-space: nowrap;
  }
  .sub {
    padding-left: 12px;
  }
  .leaf {
    padding-left: 24px;
  }
  .middle {
    display: flex;
    flex-direction: column;
    gap: 4px;
    min-height: 0;
  }
  .types {
    display: flex;
    flex-wrap: wrap;
    gap: 2px;
  }
  .type {
    display: flex;
    flex-direction: column;
    align-items: center;
    width: 66px;
    min-height: 44px;
    padding: 2px;
    font-size: 10px;
  }
  .type.on {
    border-color: var(--dark) var(--hilite) var(--hilite) var(--dark);
    background: #c9d4ea;
  }
  .page {
    flex: 1;
    min-height: 0;
    padding: 6px;
    overflow: auto;
    background: #8e9aaf;
    border: 1px solid var(--shadow);
  }
  .paper {
    max-width: 900px;
    margin: 0 auto;
    padding: 10px;
    background: #fff;
    box-shadow: 2px 2px 0 #555;
  }
  .details {
    display: grid;
    gap: 6px;
    align-content: start;
    overflow: auto;
  }
  .form {
    display: grid;
    grid-template-columns: auto minmax(0, 1fr);
    gap: 4px 6px;
    align-items: center;
  }
  .form .field {
    min-width: 0;
    width: 100%;
  }
  .half {
    width: 50%;
  }
  .end {
    justify-content: flex-end;
    margin-top: 4px;
  }
</style>
