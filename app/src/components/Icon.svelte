<script lang="ts">
  // 16-px line icons in the style of design/mockups (drawn here, no icon dependency).
  interface Props {
    name: string;
    size?: number;
  }
  let { name, size = 16 }: Props = $props();

  const PATHS: Record<string, string> = {
    open: "M2 4h4l1.5 1.5H14v7.5H2z M2 7h12",
    save: "M3 2h8l2 2v10H3z M5 2v4h6V2 M5 14v-4h6v4",
    import: "M8 2v8 M5 7l3 3 3-3 M3 12v2h10v-2",
    export: "M8 10V2 M5 5l3-3 3 3 M3 12v2h10v-2",
    fit: "M2 14V2 M2 14h12 M3 12c3-1 5-4 7-7 1.2-1.6 2.5-2.5 3.5-3",
    validate: "M4 3l9 5-9 5z",
    stop: "M4 4h8v8H4z",
    report: "M4 2h6l3 3v9H4z M10 2v3h3 M6 8h5 M6 10h5 M6 12h3",
    check: "M3 8.5l3 3 7-7",
    consistency: "M2 6c2-2 4 2 6 0s4-2 6 0 M2 10c2-2 4 2 6 0s4-2 6 0",
    table: "M2 3h12v10H2z M2 6h12 M2 9.5h12 M6 3v10 M10 3v10",
    chart: "M2 14V2 M2 14h12 M4 11l3-4 3 2 4-5",
    calc: "M3 2h10v12H3z M5 4h6v2H5z M5 8h1 M8 8h1 M11 8h0.5 M5 11h1 M8 11h1 M11 11h0.5",
    gear: "M8 5.5a2.5 2.5 0 1 0 0 5 2.5 2.5 0 0 0 0-5z M8 1.5v2 M8 12.5v2 M1.5 8h2 M12.5 8h2 M3.4 3.4l1.4 1.4 M11.2 11.2l1.4 1.4 M3.4 12.6l1.4-1.4 M11.2 4.8l1.4-1.4",
    folder: "M2 4h4l1.5 1.5H14v7.5H2z",
    code: "M5 4L1.5 8 5 12 M11 4l3.5 4-3.5 4 M9.5 3l-3 10",
    results: "M2 14V2 M2 14h12 M4 14V9h2v5 M8 14V5h2v9 M12 14V7h1.5v7",
    box: "M2 5l6-3 6 3v6l-6 3-6-3z M2 5l6 3 6-3 M8 8v6",
  };
</script>

<svg width={size} height={size} viewBox="0 0 16 16" aria-hidden="true" class="icon">
  <path d={PATHS[name] ?? PATHS.box} fill="none" stroke="currentColor" stroke-width="1.2" stroke-linejoin="round" stroke-linecap="round" />
</svg>

<style>
  .icon {
    display: block;
    flex-shrink: 0;
  }
</style>
