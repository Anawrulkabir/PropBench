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

  type Kind = "property" | "errorbars" | "deviation" | "parity" | "pt" | "histogram" | "qq";
  const TYPES: { id: Kind | string; label: string; icon: string; enabled: boolean }[] = [
    { id: "property", label: "Line + symbol", icon: "chart", enabled: true },
    { id: "errorbars", label: "Error bars", icon: "chart", enabled: true },
    { id: "deviation", label: "Deviation", icon: "fit", enabled: true },
    { id: "parity", label: "Parity", icon: "fit", enabled: true },
    { id: "pt", label: "p–T diagram", icon: "chart", enabled: true },
    { id: "histogram", label: "Deviation histogram", icon: "results", enabled: true },
    { id: "qq", label: "Residual Q–Q", icon: "results", enabled: true },
    ...["Column", "Box", "Contour", "Heat map", "Ternary", "Polar", "p–h diagram", "T–s diagram"].map(
      (label) => ({ id: label, label, icon: "results", enabled: false }),
    ),
  ];
  // Journal presets as rendered by the worker (propbench.figures.PRESETS).
  let PRESETS = $state([
    { id: "elsevier1", label: "Elsevier, 1 column (90 mm)", mm: 90 },
    { id: "elsevier15", label: "Elsevier, 1.5 columns (140 mm)", mm: 140 },
    { id: "elsevier2", label: "Elsevier, 2 columns (190 mm)", mm: 190 },
    { id: "acs1", label: "ACS, 1 column (3.25 in)", mm: 82.55 },
    { id: "acs2", label: "ACS, 2 columns (7 in)", mm: 177.8 },
    { id: "springer1", label: "Springer, 1 column (84 mm)", mm: 84 },
    { id: "springer2", label: "Springer, 2 columns (174 mm)", mm: 174 },
    { id: "aip1", label: "AIP, 1 column (3.37 in)", mm: 85.6 },
  ]);
  interface Template {
    name: string;
    kind: Kind;
    title: string;
    xLabel: string;
    yLabel: string;
    ranges: [string, string, string, string];
    logX: boolean;
    logY: boolean;
    markerSize: number;
    errorBars: boolean;
    legend: boolean;
    preset: string;
    aspect: number;
    fontSize: number | null;
    colors: Record<string, string>;
  }

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
  let format = $state<"svg" | "pdf" | "eps" | "png" | "tiff">("pdf");
  let logX = $state(false);
  let logY = $state(false);
  let aspect = $state(0.75);
  let fontSize = $state<number | null>(null);
  let xLabelOverride = $state("");
  let yLabelOverride = $state("");
  let colors = $state<Record<string, string>>({});
  let preview = $state<string | null>(null);
  let templateName = $state("");
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

  type Built = { series: Series[]; lines: Line[]; x: string; y: string; band: [number, number] | null; zero: boolean; values?: number[] };

  function build(kind: Kind): Built {
    const ds = project.activeDatasets();
    if (kind === "pt") {
      return {
        series: ds.filter((d) => d.pressure).map((d) => ({ name: d.name, x: d.temperature, y: (d.pressure ?? []).map((p) => p * 1e-6) })),
        lines: [], x: "Temperature, T / K", y: "Pressure, p / MPa", band: null, zero: false,
      };
    }
    const fitted = project.candidates.find((c) => c.label === model?.label)?.fit;
    if (kind === "deviation" || kind === "histogram" || kind === "qq") {
      const row = project.comparison?.rows.filter((r) => r.model === model?.label && r.point_ids);
      const series: Series[] = fitted
        ? deviationSeries(fitted)
        : row?.length
          ? pointSeries(project.datasets, row.flatMap((r) => r.point_ids?.map(() => r.dataset) ?? []), row.flatMap((r) => r.point_ids ?? []), row.flatMap((r) => r.ard ?? []))
          : [];
      const devLabel = `100 (${unit.symbol}exp − ${unit.symbol}model)/${unit.symbol}model`;
      const values = series.flatMap((s) => s.y.filter((v): v is number => v !== null));
      if (kind === "histogram") return { series: [], lines: [], x: devLabel, y: "Number of points", band: null, zero: false, values };
      if (kind === "qq") return { series: [], lines: [], x: "Normal quantile", y: devLabel, band: null, zero: false, values };
      return { series, lines: [], x: "Temperature, T / K", y: devLabel, band: null, zero: true };
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
  }

  const data = $derived(build(kind));
  const shownSeries = $derived(data.series.filter((s) => !hidden[s.name]));
  const shownLines = $derived(data.lines.filter((l) => !hidden[l.name]));
  const range = (a: string, b: string): [number, number] | null =>
    a.trim() !== "" && b.trim() !== "" && Number.isFinite(Number(a)) && Number.isFinite(Number(b)) ? [Number(a), Number(b)] : null;

  function download(blob: Blob, name: string) {
    const url = URL.createObjectURL(blob);
    const a = document.createElement("a");
    a.href = url;
    a.download = name;
    a.click();
    setTimeout(() => URL.revokeObjectURL(url), 1000);
  }

  const MARKERS = ["square", "triangle", "circle", "diamond", "down", "plus", "cross"];

  /** The figure as a spec for the worker's renderer (propbench.figures). */
  function figureSpec(k: Kind = kind): object {
    const b = k === kind ? data : build(k);
    const hide = (n: string) => k === kind && hidden[n];
    const layers: object[] = [];
    if (b.zero) layers.push({ type: "hline", y: 0 });
    if (b.band) layers.push({ type: "band", range: b.band });
    b.series.filter((s) => !hide(s.name)).forEach((s, i) =>
      layers.push({ type: "points", name: s.name, x: s.x, y: s.y, err: errorBars || k === "errorbars" ? (s.err ?? undefined) : undefined, color: colors[s.name], marker: MARKERS[i % MARKERS.length], open: s.open }),
    );
    for (const l of b.lines.filter((l) => !hide(l.name))) layers.push({ type: "line", name: l.name, x: l.x, y: l.y, color: colors[l.name] ?? l.color, dashed: l.dashed });
    if (k === "histogram" && b.values) layers.push({ type: "histogram", name: model?.label ?? "", values: b.values, bins: 20 });
    if (k === "qq" && b.values) layers.push({ type: "qq", name: model?.label ?? "", values: b.values });
    const r = (a: string, c: string) => (k === kind ? range(a, c) : null);
    return {
      preset,
      aspect,
      font_size: fontSize ?? undefined,
      marker_size: markerSize * 0.9,
      title: title || undefined,
      legend,
      x: { label: (k === kind && xLabelOverride) || b.x, log: k === kind && logX, range: r(xFrom, xTo) },
      y: { label: (k === kind && yLabelOverride) || b.y, log: k === kind && logY, range: r(yFrom, yTo) },
      layers,
    };
  }

  async function render(fmt: string, d: number, k: Kind = kind) {
    return worker<{ content_base64: string; mime: string; bytes: number; width_px: number | null }>("figure.render", { spec: figureSpec(k), format: fmt, dpi: d });
  }

  function blobOf(r: { content_base64: string; mime: string }): Blob {
    const bin = atob(r.content_base64);
    const bytes = new Uint8Array(bin.length);
    for (let i = 0; i < bin.length; i++) bytes[i] = bin.charCodeAt(i);
    return new Blob([bytes], { type: r.mime });
  }

  async function exportFigure() {
    busy = true;
    error = null;
    try {
      const r = await render(format, dpi);
      download(blobOf(r), `propbench-${kind}.${format}`);
      const size = r.width_px ? `, ${r.width_px} px wide (${dpi} dpi)` : "";
      project.note(`Figure exported as ${format.toUpperCase()} (${PRESETS.find((p) => p.id === preset)?.label}${size})`);
    } catch (err) {
      error = errorMessage(err);
    } finally {
      busy = false;
    }
  }

  async function exactPreview() {
    busy = true;
    error = null;
    try {
      const r = await render("png", 150);
      if (preview) URL.revokeObjectURL(preview);
      preview = URL.createObjectURL(blobOf(r));
    } catch (err) {
      error = errorMessage(err);
    } finally {
      busy = false;
    }
  }

  /** The standard figures of a property paper: state map, data with model curves, deviations, histogram, Q–Q. */
  async function exportSet() {
    busy = true;
    error = null;
    const kinds: Kind[] = ["pt", "property", ...((model ? ["deviation", "histogram", "qq"] : []) as Kind[])];
    try {
      for (const [i, k] of kinds.entries()) {
        const r = await render(format, dpi, k);
        download(blobOf(r), `figure${i + 1}-${k}.${format}`);
      }
      project.note(`Figure set exported: ${kinds.length} ${format.toUpperCase()} files (${kinds.join(", ")})`);
    } catch (err) {
      error = errorMessage(err);
    } finally {
      busy = false;
    }
  }

  const templates = $derived((project.tools as { graphTemplates?: Template[] }).graphTemplates ?? []);

  function saveTemplate() {
    const name = templateName.trim() || `Template ${templates.length + 1}`;
    const t: Template = { name, kind, title, xLabel: xLabelOverride, yLabel: yLabelOverride, ranges: [xFrom, xTo, yFrom, yTo], logX, logY, markerSize, errorBars, legend, preset, aspect, fontSize, colors: { ...colors } };
    const tools = project.tools as { graphTemplates?: Template[] };
    tools.graphTemplates = [...templates.filter((x) => x.name !== name), t];
    templateName = "";
    project.note(`Graph template saved: ${name}`);
  }

  function applyTemplate(name: string) {
    const t = templates.find((x) => x.name === name);
    if (!t) return;
    ({ kind, title, markerSize, errorBars, legend, preset, aspect, fontSize, logX, logY } = t);
    [xFrom, xTo, yFrom, yTo] = t.ranges;
    xLabelOverride = t.xLabel;
    yLabelOverride = t.yLabel;
    colors = { ...t.colors };
  }

  $effect(() => {
    worker<{ presets: { id: string; label: string; width_mm: number }[] }>("figure.presets")
      .then((r) => (PRESETS = r.presets.map((p) => ({ id: p.id, label: p.label, mm: p.width_mm }))))
      .catch(() => undefined);
  });
</script>

<div class="studio">
  <aside class="objects well">
    <div class="head">Object manager</div>
    <div class="node">▣ Graph1 ({PRESETS.find((p) => p.id === preset)?.mm} mm)</div>
    <div class="node sub">🗀 Layer 1: {TYPES.find((t) => t.id === kind)?.label}</div>
    {#each data.series as s, i (s.name)}
      <label class="leaf"><input type="checkbox" checked={!hidden[s.name]} onchange={() => (hidden[s.name] = !hidden[s.name])} /> <input type="color" class="swatch" value={colors[s.name] ?? SERIES_COLORS[i % SERIES_COLORS.length]} oninput={(e) => (colors[s.name] = (e.currentTarget as HTMLInputElement).value)} aria-label="Colour of {s.name}" /> {s.name}</label>
    {/each}
    {#each data.lines as l (l.name)}
      <label class="leaf"><input type="checkbox" checked={!hidden[l.name]} onchange={() => (hidden[l.name] = !hidden[l.name])} /> ƒ {l.name}</label>
    {/each}
    <div class="head tpl">Templates</div>
    {#each templates as t (t.name)}<button class="leaf linkish" onclick={() => applyTemplate(t.name)}>▤ {t.name}</button>{:else}<div class="leaf muted">(none saved)</div>{/each}
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
      {#if preview}
        <div class="paper exact"><img src={preview} alt="Export preview" /><button class="btn" onclick={() => (preview = null)}>Back to the editable plot</button></div>
      {:else if kind === "histogram" || kind === "qq"}
        <div class="paper"><p class="muted">{data.values?.length ? `${data.values.length} deviations of ${model?.label}: drawn by the exporter — use Exact preview.` : "Fit a model (or compare models) to get deviations."}</p></div>
      {:else if project.datasets.length}
        <div class="paper">
          <ScatterPlot
            series={shownSeries}
            lines={shownLines}
            xLabel={xLabelOverride || data.x}
            yLabel={yLabelOverride || data.y}
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
        <label for="g-xl">X label</label>
        <input id="g-xl" class="field" bind:value={xLabelOverride} placeholder={data.x} />
        <label for="g-yl">Y label</label>
        <input id="g-yl" class="field" bind:value={yLabelOverride} placeholder={data.y} />
        <span>X from / to</span>
        <span class="row"><input class="field num half" bind:value={xFrom} placeholder="auto" /><input class="field num half" bind:value={xTo} placeholder="auto" /></span>
        <span>Y from / to</span>
        <span class="row"><input class="field num half" bind:value={yFrom} placeholder="auto" /><input class="field num half" bind:value={yTo} placeholder="auto" /></span>
        <span>Log scale</span>
        <span class="row"><label class="row"><input type="checkbox" bind:checked={logX} /> x</label><label class="row"><input type="checkbox" bind:checked={logY} /> y</label></span>
        <label for="g-aspect">Height / width</label>
        <input id="g-aspect" class="field" type="number" min="0.3" max="1.5" step="0.05" bind:value={aspect} />
        <label for="g-font">Font size (pt)</label>
        <input id="g-font" class="field" type="number" min="5" max="14" step="0.5" bind:value={fontSize} placeholder="preset" />
      </div>
    </fieldset>
    <fieldset class="group">
      <legend>Export</legend>
      <div class="form">
        <label for="g-fmt">Format</label>
        <select id="g-fmt" class="field" bind:value={format}>
          <option value="pdf">PDF (vector)</option><option value="svg">SVG (vector)</option><option value="eps">EPS (vector)</option>
          <option value="png">PNG</option><option value="tiff">TIFF</option>
        </select>
        <label for="g-dpi">Resolution</label>
        <select id="g-dpi" class="field" bind:value={dpi} disabled={format === "svg" || format === "pdf" || format === "eps"}>
          {#each [300, 600, 1200, 2500] as d (d)}<option value={d}>{d} dpi</option>{/each}
        </select>
        <label for="g-preset">Preset</label>
        <select id="g-preset" class="field" bind:value={preset}>{#each PRESETS as p (p.id)}<option value={p.id}>{p.label}</option>{/each}</select>
      </div>
      <div class="row end">
        <button class="btn" onclick={exactPreview} disabled={busy || !project.datasets.length}>Exact preview</button>
        <button class="btn default" onclick={exportFigure} disabled={busy || !project.datasets.length}>Export</button>
      </div>
      <div class="row end"><button class="btn" onclick={exportSet} disabled={busy || !project.datasets.length}>Export figure set</button></div>
      <div class="row"><input class="field grow" bind:value={templateName} placeholder="template name" aria-label="Template name" /><button class="btn" onclick={saveTemplate}>Save template</button></div>
      <p class="muted">Rendered by matplotlib: one plot per figure, legend inside the axes, journal sizes and fonts.</p>
    </fieldset>
  </aside>
</div>

<style>
  .studio {
    display: grid;
    grid-template-columns: 180px minmax(0, 1fr) 250px;
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
    min-width: 0;
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
  .grow {
    flex: 1;
  }
  .swatch {
    width: 16px;
    height: 14px;
    padding: 0;
    border: 1px solid var(--shadow);
  }
  .tpl {
    margin-top: 10px;
  }
  .linkish {
    padding: 0 0 0 24px;
    text-align: left;
    background: none;
    border: none;
  }
  .exact img {
    display: block;
    max-width: 100%;
    margin: 0 auto 6px;
  }
</style>
