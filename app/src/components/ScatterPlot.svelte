<script lang="ts">
  // Scatter plot in SVG: one plot per figure, legend inside the plot area (CLAUDE.md figure conventions).
  import { type Line, linearScale, type Series, SERIES_COLORS, SERIES_SHAPES, type Shape, tickLabel } from "../lib/plot";

  interface Props {
    series: Series[];
    lines?: Line[];
    xLabel: string;
    yLabel: string;
    band?: [number, number] | null;
    bandLabel?: string;
    zeroLine?: boolean;
    height?: number;
  }

  let { series, lines = [], xLabel, yLabel, band = null, bandLabel = "", zeroLine = false, height = 300 }: Props =
    $props();

  const W = 640;
  const M = { left: 58, right: 16, top: 12, bottom: 40 };

  const xs = $derived([...series.flatMap((s) => s.x), ...lines.flatMap((l) => l.x)]);
  const ys = $derived([
    ...series.flatMap((s) => s.y),
    ...series.flatMap((s) => (s.err ? s.y.map((y, i) => (y === null ? null : y + (s.err?.[i] ?? 0))) : [])),
    ...series.flatMap((s) => (s.err ? s.y.map((y, i) => (y === null ? null : y - (s.err?.[i] ?? 0))) : [])),
    ...lines.flatMap((l) => l.y),
    ...(band ? band : []),
  ]);
  const sx = $derived(linearScale(xs, [M.left, W - M.right], 7));
  const sy = $derived(linearScale(ys, [height - M.bottom, M.top], 6, zeroLine ? 0 : undefined));

  const styled = $derived(
    series.map((s, i) => ({
      ...s,
      color: s.color ?? SERIES_COLORS[i % SERIES_COLORS.length],
      shape: s.shape ?? SERIES_SHAPES[i % SERIES_SHAPES.length],
    })),
  );

  const legendWidth = $derived(
    24 + 5.6 * Math.max(0, ...styled.map((s) => s.name.length), ...lines.map((l) => l.name.length), band ? bandLabel.length : 0),
  );

  function path(l: Line): string {
    let d = "";
    let pen = false;
    l.x.forEach((x, i) => {
      const y = l.y[i];
      if (y === null || !Number.isFinite(y)) {
        pen = false;
        return;
      }
      d += `${pen ? "L" : "M"}${sx.map(x).toFixed(1)},${sy.map(y).toFixed(1)}`;
      pen = true;
    });
    return d;
  }

  function marker(shape: Shape, x: number, y: number): string {
    const r = 4;
    switch (shape) {
      case "square":
        return `M${x - r},${y - r}h${2 * r}v${2 * r}h${-2 * r}z`;
      case "triangle":
        return `M${x},${y - r - 1}L${x + r + 1},${y + r}L${x - r - 1},${y + r}z`;
      case "diamond":
        return `M${x},${y - r - 1}L${x + r + 1},${y}L${x},${y + r + 1}L${x - r - 1},${y}z`;
      default:
        return `M${x - r},${y}a${r},${r} 0 1,0 ${2 * r},0a${r},${r} 0 1,0 ${-2 * r},0`;
    }
  }
</script>

<svg viewBox="0 0 {W} {height}" class="plot" role="img" aria-label="{yLabel} against {xLabel}">
  <rect x={M.left} y={M.top} width={W - M.left - M.right} height={height - M.top - M.bottom} fill="#fff" />
  {#if band}
    <rect
      x={M.left}
      width={W - M.left - M.right}
      y={sy.map(band[1])}
      height={Math.max(0, sy.map(band[0]) - sy.map(band[1]))}
      fill="#c9d8c6"
      opacity="0.6"
    />
  {/if}
  {#each sy.ticks as t (t)}
    <line x1={M.left} x2={W - M.right} y1={sy.map(t)} y2={sy.map(t)} stroke="#eceae2" />
    <text x={M.left - 6} y={sy.map(t) + 3.5} text-anchor="end">{tickLabel(t)}</text>
  {/each}
  {#each sx.ticks as t (t)}
    <line x1={sx.map(t)} x2={sx.map(t)} y1={height - M.bottom} y2={height - M.bottom + 4} stroke="#000" />
    <text x={sx.map(t)} y={height - M.bottom + 15} text-anchor="middle">{tickLabel(t)}</text>
  {/each}
  {#if zeroLine && sy.domain[0] <= 0 && sy.domain[1] >= 0}
    <line x1={M.left} x2={W - M.right} y1={sy.map(0)} y2={sy.map(0)} stroke="#000" />
  {/if}
  <line x1={M.left} x2={M.left} y1={M.top} y2={height - M.bottom} stroke="#000" />
  <line x1={M.left} x2={W - M.right} y1={height - M.bottom} y2={height - M.bottom} stroke="#000" />
  {#each lines as l, i (l.name + i)}
    <path d={path(l)} fill="none" stroke={l.color ?? "#333"} stroke-width="1.2" stroke-dasharray={l.dashed ? "5 3" : ""} />
  {/each}
  {#each styled as s, i (s.name + i)}
    {#each s.x as x, j (j)}
      {@const y = s.y[j]}
      {#if y !== null && Number.isFinite(y) && s.err?.[j]}
        {@const e = s.err[j] ?? 0}
        <path
          d="M{sx.map(x)},{sy.map(y - e)}V{sy.map(y + e)}M{sx.map(x) - 3},{sy.map(y - e)}h6M{sx.map(x) - 3},{sy.map(y + e)}h6"
          stroke={s.color}
          fill="none"
        />
      {/if}
      {#if y !== null && Number.isFinite(y)}
        <path d={marker(s.shape, sx.map(x), sy.map(y))} fill={s.open ? "none" : s.color} stroke={s.color} stroke-width="1.2">
          <title>{s.name}: {tickLabel(x)}, {tickLabel(y)}</title>
        </path>
      {/if}
    {/each}
  {/each}
  <text x={(M.left + W - M.right) / 2} y={height - 6} text-anchor="middle" class="label">{xLabel}</text>
  <text transform="translate(13 {(M.top + height - M.bottom) / 2}) rotate(-90)" text-anchor="middle" class="label">{yLabel}</text>
  <g transform="translate({M.left + 8} {M.top + 6})">
    <rect
      x="-4"
      y="-3"
      width={legendWidth}
      height={(styled.length + lines.length + (band && bandLabel ? 1 : 0)) * 14 + 4}
      fill="#fff"
      opacity="0.85"
      stroke="#c4c0b8"
    />
    {#each styled as s, i (s.name + i)}
      <g transform="translate(0 {i * 14})">
        <path d={marker(s.shape, 6, 6)} fill={s.open ? "none" : s.color} stroke={s.color} />
        <text x="16" y="10">{s.name}</text>
      </g>
    {/each}
    {#each lines as l, i (l.name + i)}
      <g transform="translate(0 {(styled.length + i) * 14})">
        <line x1="0" x2="12" y1="6" y2="6" stroke={l.color ?? "#333"} stroke-dasharray={l.dashed ? "4 2" : ""} />
        <text x="16" y="10">{l.name}</text>
      </g>
    {/each}
    {#if band && bandLabel}
      <g transform="translate(0 {(styled.length + lines.length) * 14})">
        <rect width="12" height="9" y="2" fill="#c9d8c6" />
        <text x="16" y="10">{bandLabel}</text>
      </g>
    {/if}
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
