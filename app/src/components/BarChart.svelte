<script lang="ts">
  // Grouped bar chart in SVG (e.g. cross-validation AARD per candidate and method).
  import { linearScale, SERIES_COLORS, tickLabel } from "../lib/plot";

  interface Props {
    groups: { label: string; values: (number | null)[] }[];
    seriesNames: string[];
    yLabel: string;
    reference?: { value: number; label: string } | null;
    height?: number;
  }
  let { groups, seriesNames, yLabel, reference = null, height = 240 }: Props = $props();

  const W = 640;
  const M = { left: 52, right: 16, top: 14, bottom: 34 };
  const values = $derived([...groups.flatMap((g) => g.values), ...(reference ? [reference.value] : [])]);
  const sy = $derived(linearScale(values, [height - M.bottom, M.top], 5, 0));
  const slot = $derived((W - M.left - M.right) / Math.max(1, groups.length));
  const bar = $derived(Math.min(36, (slot * 0.7) / Math.max(1, seriesNames.length)));
</script>

<svg viewBox="0 0 {W} {height}" class="plot" role="img" aria-label={yLabel}>
  <rect x={M.left} y={M.top} width={W - M.left - M.right} height={height - M.top - M.bottom} fill="#fff" />
  {#each sy.ticks as t (t)}
    <line x1={M.left} x2={W - M.right} y1={sy.map(t)} y2={sy.map(t)} stroke="#eceae2" />
    <text x={M.left - 6} y={sy.map(t) + 3.5} text-anchor="end">{tickLabel(t)}</text>
  {/each}
  {#each groups as g, i (g.label + i)}
    {@const x0 = M.left + i * slot + (slot - bar * seriesNames.length) / 2}
    {#each g.values as v, j (j)}
      {#if v !== null && Number.isFinite(v)}
        <rect
          x={x0 + j * bar}
          width={bar - 2}
          y={sy.map(Math.max(v, 0))}
          height={Math.max(0, sy.map(0) - sy.map(Math.max(v, 0)))}
          fill={SERIES_COLORS[j % SERIES_COLORS.length]}
        >
          <title>{g.label}, {seriesNames[j]}: {tickLabel(v)}</title>
        </rect>
      {/if}
    {/each}
    <text x={M.left + (i + 0.5) * slot} y={height - M.bottom + 14} text-anchor="middle">{g.label}</text>
  {/each}
  {#if reference}
    <line
      x1={M.left}
      x2={W - M.right}
      y1={sy.map(reference.value)}
      y2={sy.map(reference.value)}
      stroke="#333"
      stroke-dasharray="4 3"
    />
    <text x={W - M.right - 4} y={sy.map(reference.value) - 4} text-anchor="end">{reference.label}</text>
  {/if}
  <line x1={M.left} x2={M.left} y1={M.top} y2={height - M.bottom} stroke="#000" />
  <line x1={M.left} x2={W - M.right} y1={sy.map(0)} y2={sy.map(0)} stroke="#000" />
  <text transform="translate(13 {(M.top + height - M.bottom) / 2}) rotate(-90)" text-anchor="middle" class="label">{yLabel}</text>
  <g transform="translate({M.left + 8} {M.top + 6})">
    {#each seriesNames as name, j (name)}
      <g transform="translate({j * 110} 0)">
        <rect width="10" height="10" fill={SERIES_COLORS[j % SERIES_COLORS.length]} />
        <text x="14" y="9">{name}</text>
      </g>
    {/each}
  </g>
</svg>

<style>
  .plot {
    display: block;
    width: 100%;
    height: auto;
    font-family: Tahoma, "Segoe UI", Verdana, sans-serif;
    font-size: 10px;
  }
  .label {
    font-size: 11px;
  }
</style>
