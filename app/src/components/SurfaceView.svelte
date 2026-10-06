<script lang="ts">
  // 3D view (design/mockups/15_Surface3D): model surface η(T, p) computed by the worker on a grid, drawn with a
  // simple projection (drag to rotate), measured points as overlay. Liquid region only by default (p > p_sat).
  import { errorMessage, worker } from "../lib/api";
  import { project } from "../lib/project.svelte";
  import { display } from "../lib/quantities";
  import { turbo } from "../lib/surface";
  import type { ModelSpec } from "../lib/types";

  let modelKey = $state("");
  let references = $state<{ label: string; model: ModelSpec }[]>([]);
  let az = $state(35);
  let el = $state(25);
  let wireframe = $state(true);
  let showPoints = $state(true);
  let liquidOnly = $state(true);
  let opacity = $state(0.9);
  let grid = $state<{ t: number[]; p: number[]; z: (number | null)[][] } | null>(null);
  let busy = $state(false);
  let error = $state<string | null>(null);

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

  async function compute() {
    if (!model) return;
    error = null;
    busy = true;
    try {
      const ds = project.datasets.filter((d) => d.pressure);
      const ts = ds.flatMap((d) => d.temperature);
      const ps = ds.flatMap((d) => d.pressure ?? []);
      const nT = 15;
      const nP = 8;
      const t = Array.from({ length: nT }, (_, i) => Math.min(...ts) - 5 + ((Math.max(...ts) - Math.min(...ts) + 10) * i) / (nT - 1));
      const p = Array.from({ length: nP }, (_, j) => Math.max(1e5, Math.min(...ps) * 0.5) + ((Math.max(...ps) * 1.1 - Math.max(1e5, Math.min(...ps) * 0.5)) * j) / (nP - 1));
      const tt = t.flatMap((x) => p.map(() => x));
      const pp = t.flatMap(() => p);
      const r = await worker<{ values: (number | null)[] }>("model.predict", { model: model.spec, temperature: tt, pressure: pp });
      let psat: (number | null)[] = t.map(() => null);
      if (liquidOnly) {
        const sat = await worker<{ outputs: Record<string, (number | null)[]> }>("properties", {
          fluid, pair: "QT_INPUTS", values1: t.map(() => 0), values2: t, outputs: ["P"],
        });
        psat = sat.outputs.P;
      }
      grid = {
        t,
        p,
        z: t.map((_, i) =>
          p.map((pj, j) => {
            const v = r.values[i * nP + j];
            const ps = psat[i];
            return v === null || (liquidOnly && ps !== null && pj < ps) ? null : v * unit.factor;
          }),
        ),
      };
      project.note(`3D view: ${model.label} on a ${nT} × ${nP} grid${liquidOnly ? " (liquid only)" : ""}`);
    } catch (err) {
      error = errorMessage(err);
    } finally {
      busy = false;
    }
  }

  // --- projection ---
  const W = 640;
  const H = 440;
  const ranges = $derived.by(() => {
    const g = grid;
    if (!g) return null;
    const zs = g.z.flat().filter((v): v is number => v !== null);
    const pts = project.datasets.flatMap((d) => d.values.map((v) => v * unit.factor));
    const all = [...zs, ...(showPoints ? pts : [])];
    return {
      t: [g.t[0], g.t[g.t.length - 1]],
      p: [g.p[0], g.p[g.p.length - 1]],
      z: [Math.min(...all), Math.max(...all)],
    };
  });

  function project3(t: number, p: number, z: number): [number, number, number] {
    if (!ranges) return [0, 0, 0];
    const x = ((t - ranges.t[0]) / (ranges.t[1] - ranges.t[0]) - 0.5) * 2;
    const y = ((p - ranges.p[0]) / (ranges.p[1] - ranges.p[0]) - 0.5) * 2;
    const h = ((z - ranges.z[0]) / (ranges.z[1] - ranges.z[0] || 1) - 0.5) * 1.6;
    const a = (az * Math.PI) / 180;
    const e = (el * Math.PI) / 180;
    const xr = x * Math.cos(a) - y * Math.sin(a);
    const yr = x * Math.sin(a) + y * Math.cos(a);
    const sx = W / 2 + xr * 170;
    const sy = H / 2 + 20 - (h * Math.cos(e) - yr * Math.sin(e)) * 150;
    const depth = yr * Math.cos(e) + h * Math.sin(e);
    return [sx, sy, depth];
  }

  const quads = $derived.by(() => {
    const g = grid;
    if (!g || !ranges) return [];
    const out: { d: string; depth: number; fill: string }[] = [];
    for (let i = 0; i < g.t.length - 1; i++) {
      for (let j = 0; j < g.p.length - 1; j++) {
        const corners = [
          [i, j],
          [i + 1, j],
          [i + 1, j + 1],
          [i, j + 1],
        ].map(([a, b]) => ({ t: g.t[a], p: g.p[b], z: g.z[a][b] }));
        if (corners.some((c) => c.z === null)) continue;
        const pr = corners.map((c) => project3(c.t, c.p, c.z as number));
        const zMean = corners.reduce((s, c) => s + (c.z as number), 0) / 4;
        out.push({
          d: `M${pr.map((q) => `${q[0].toFixed(1)},${q[1].toFixed(1)}`).join("L")}Z`,
          depth: pr.reduce((s, q) => s + q[2], 0) / 4,
          fill: turbo((zMean - ranges.z[0]) / (ranges.z[1] - ranges.z[0] || 1)),
        });
      }
    }
    return out.sort((a, b) => b.depth - a.depth);
  });

  const points = $derived.by(() => {
    if (!grid || !ranges || !showPoints) return [];
    return project.datasets
      .filter((d) => d.pressure)
      .flatMap((d) =>
        d.values.map((v, i) => {
          const [x, y] = project3(d.temperature[i], d.pressure?.[i] ?? 0, v * unit.factor);
          return { x, y, key: `${d.name}:${i}`, title: `${d.name}: ${d.temperature[i].toFixed(2)} K, ${((d.pressure?.[i] ?? 0) * 1e-6).toFixed(3)} MPa` };
        }),
      );
  });

  const axes = $derived.by(() => {
    if (!ranges) return null;
    const o = project3(ranges.t[0], ranges.p[0], ranges.z[0]);
    const xt = project3(ranges.t[1], ranges.p[0], ranges.z[0]);
    const yp = project3(ranges.t[0], ranges.p[1], ranges.z[0]);
    const zh = project3(ranges.t[0], ranges.p[0], ranges.z[1]);
    return { o, xt, yp, zh };
  });

  function drag(e: PointerEvent) {
    const start = { x: e.clientX, y: e.clientY, az, el };
    const move = (m: PointerEvent) => {
      az = Math.round(start.az + (m.clientX - start.x) * 0.5);
      el = Math.max(-10, Math.min(85, Math.round(start.el + (m.clientY - start.y) * 0.3)));
    };
    const up = () => {
      window.removeEventListener("pointermove", move);
      window.removeEventListener("pointerup", up);
    };
    window.addEventListener("pointermove", move);
    window.addEventListener("pointerup", up);
  }
</script>

<div class="surface">
  <div class="canvas-col">
    <div class="bar row muted">Drag to rotate · the surface is computed by the worker from the chosen model</div>
    <div class="well canvas" role="img" aria-label="3D surface" onpointerdown={drag}>
      {#if grid && axes}
        <svg viewBox="0 0 {W} {H}">
          {#each quads as q, k (k)}
            <path d={q.d} fill={q.fill} fill-opacity={opacity} stroke={wireframe ? "rgba(0,0,0,0.35)" : "none"} stroke-width="0.6" />
          {/each}
          <line x1={axes.o[0]} y1={axes.o[1]} x2={axes.xt[0]} y2={axes.xt[1]} stroke="#000" />
          <line x1={axes.o[0]} y1={axes.o[1]} x2={axes.yp[0]} y2={axes.yp[1]} stroke="#000" />
          <line x1={axes.o[0]} y1={axes.o[1]} x2={axes.zh[0]} y2={axes.zh[1]} stroke="#000" />
          <text x={axes.xt[0]} y={axes.xt[1] + 14} text-anchor="middle">T / K ({ranges?.t[0].toFixed(0)}–{ranges?.t[1].toFixed(0)})</text>
          <text x={axes.yp[0]} y={axes.yp[1] + 14} text-anchor="middle">p / MPa ({((ranges?.p[0] ?? 0) * 1e-6).toFixed(1)}–{((ranges?.p[1] ?? 0) * 1e-6).toFixed(1)})</text>
          <text x={axes.zh[0]} y={axes.zh[1] - 6} text-anchor="middle">{unit.symbol} / {unit.unit}</text>
          {#each points as pt (pt.key)}
            <circle cx={pt.x} cy={pt.y} r="3.5" fill="#fff" stroke="#000" stroke-width="1.2"><title>{pt.title}</title></circle>
          {/each}
        </svg>
        <div class="scale">
          {#each Array.from({ length: 10 }, (_, i) => 1 - i / 9) as f (f)}
            <div class="swatch" style="background: {turbo(f)}"></div>
          {/each}
          <div class="labels"><span>{ranges?.z[1].toFixed(0)}</span><span>{ranges?.z[0].toFixed(0)}</span></div>
        </div>
      {:else}
        <div class="empty">Choose a model and compute the surface.</div>
      {/if}
    </div>
  </div>
  <aside class="side">
    <fieldset class="group">
      <legend>Surface</legend>
      <div class="form">
        <span>Property</span><span>{unit.label} {unit.symbol}</span>
        <label for="s-model">Model</label>
        <select id="s-model" class="field" value={model?.key ?? ""} onchange={(e) => (modelKey = (e.currentTarget as HTMLSelectElement).value)}>
          {#each models as m (m.key)}<option value={m.key}>{m.label}</option>{:else}<option value="">(fit a model)</option>{/each}
        </select>
        <span>Colour map</span><span>Turbo</span>
        <label for="s-op">Opacity</label>
        <input id="s-op" class="field num" type="number" min="0.2" max="1" step="0.1" bind:value={opacity} />
      </div>
      <label class="row"><input type="checkbox" bind:checked={wireframe} /> Wireframe</label>
      <label class="row"><input type="checkbox" bind:checked={liquidOnly} /> Liquid region only (p &gt; p_sat)</label>
      <div class="row end"><button class="btn default" onclick={compute} disabled={busy || !model || !project.datasets.length}>{busy ? "Computing…" : "Compute surface"}</button></div>
      {#if error}<p class="error">{error}</p>{/if}
    </fieldset>
    <fieldset class="group">
      <legend>Overlays</legend>
      <label class="row"><input type="checkbox" bind:checked={showPoints} /> Measured points</label>
      <label class="row"><input type="checkbox" disabled /> Residual stems to surface (0.3)</label>
      <label class="row"><input type="checkbox" disabled /> 95 % uncertainty shells (0.3)</label>
    </fieldset>
    <fieldset class="group">
      <legend>Camera</legend>
      <div class="form">
        <label for="s-az">Azimuth (°)</label><input id="s-az" class="field num" type="number" bind:value={az} />
        <label for="s-el">Elevation (°)</label><input id="s-el" class="field num" type="number" min="-10" max="85" bind:value={el} />
      </div>
    </fieldset>
  </aside>
</div>

<style>
  .surface {
    display: grid;
    grid-template-columns: minmax(0, 1fr) 240px;
    gap: 6px;
    height: 100%;
    min-height: 0;
  }
  .canvas-col {
    display: flex;
    flex-direction: column;
    gap: 4px;
    min-height: 0;
  }
  .canvas {
    position: relative;
    flex: 1;
    min-height: 0;
    cursor: grab;
    background: #fff;
  }
  svg {
    width: 100%;
    height: 100%;
    font-size: 11px;
  }
  .scale {
    position: absolute;
    top: 20px;
    right: 44px;
    display: flex;
    flex-direction: column;
  }
  .swatch {
    width: 14px;
    height: 18px;
  }
  .labels {
    position: absolute;
    top: 0;
    left: 18px;
    display: flex;
    flex-direction: column;
    justify-content: space-between;
    height: 180px;
  }
  .side {
    display: grid;
    gap: 6px;
    align-content: start;
  }
  .form {
    display: grid;
    grid-template-columns: auto minmax(0, 1fr);
    gap: 4px 6px;
    align-items: center;
  }
  .form .field {
    width: 100%;
    min-width: 0;
  }
  .end {
    justify-content: flex-end;
  }
</style>
