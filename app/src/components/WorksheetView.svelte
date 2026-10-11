<script lang="ts">
  // Worksheet (design/mockups/12_Worksheet): one dataset as a table with a units row; masked rows stay in the
  // worksheet, struck through, and are left out of fits, validation and consistency.
  import { errorMessage, worker } from "../lib/api";
  import { project } from "../lib/project.svelte";
  import { display, fmt } from "../lib/quantities";

  interface Stat {
    n: number;
    mean: number | null;
    std: number | null;
    min: number | null;
    max: number | null;
    rsd: number | null;
  }
  interface Computed {
    columns: Record<string, (number | null)[]>;
    filter: boolean[];
    statistics: Record<string, Stat>;
  }

  type Key = "id" | "t" | "p" | "rho" | "value" | "u" | "phase";
  let sortKey = $state<Key>("id");
  let ascending = $state(true);
  let selection = $state<Set<number>>(new Set());

  const d = $derived(project.datasets.find((x) => x.name === project.worksheet) ?? project.datasets[0]);
  const unit = $derived(display(d?.quantity ?? "viscosity"));
  const masked = $derived(new Set(d ? (project.masks[d.name] ?? []) : []));
  const sheet = $derived(d ? (project.worksheets[d.name] ?? { formulas: [], filter: "" }) : { formulas: [], filter: "" });
  let computed = $state<Computed | null>(null);
  let formulaError = $state("");
  let editing = $state<number | null>(null);
  let draft = $state({ name: "", formula: "", unit: "" });
  let filterDraft = $state("");

  function ensureSheet() {
    if (d && !project.worksheets[d.name]) project.worksheets[d.name] = { formulas: [], filter: "" };
    return d ? project.worksheets[d.name] : null;
  }

  // Formula columns, filter and statistics are computed by the worker (the UI never computes).
  $effect(() => {
    const ds = d;
    const formulas = $state.snapshot(sheet.formulas);
    const filter = sheet.filter;
    const maskedIds = [...masked];
    if (!ds) return;
    filterDraft = filter;
    const timer = setTimeout(async () => {
      try {
        computed = await worker<Computed>("worksheet.compute", { dataset: ds, formulas, filter: filter || null, masked: maskedIds });
        formulaError = "";
      } catch (err) {
        formulaError = errorMessage(err);
      }
    }, 150);
    return () => clearTimeout(timer);
  });

  function addColumn() {
    const ws = ensureSheet();
    if (!ws) return;
    const name = `col${ws.formulas.length + 1}`;
    ws.formulas.push({ name, formula: "y", unit: "" });
    editing = ws.formulas.length - 1;
    draft = { ...ws.formulas[editing] };
  }

  function editColumn(i: number) {
    editing = i;
    draft = { ...sheet.formulas[i] };
  }

  function applyFormula() {
    const ws = ensureSheet();
    if (!ws || editing === null) return;
    ws.formulas[editing] = { name: draft.name.trim(), formula: draft.formula.trim(), unit: draft.unit.trim() };
  }

  function removeColumn() {
    const ws = ensureSheet();
    if (!ws || editing === null) return;
    ws.formulas.splice(editing, 1);
    editing = null;
  }

  function applyFilter() {
    const ws = ensureSheet();
    if (ws) ws.filter = filterDraft.trim();
  }

  const position = $derived(new Map((d?.point_ids ?? []).map((id, i) => [id, i])));

  const rows = $derived.by(() => {
    if (!d) return [];
    const out = d.point_ids.map((id, i) => ({
      id,
      t: d.temperature[i],
      p: d.pressure?.[i] ?? null,
      rho: d.molar_density?.[i] ?? null,
      value: d.values[i],
      u: d.expanded_uncertainty ? (100 * d.expanded_uncertainty[i]) / Math.abs(d.values[i]) : null,
      phase: d.phase?.[i] ?? "",
    }));
    const dir = ascending ? 1 : -1;
    return out.sort((a, b) => {
      const x = a[sortKey];
      const y = b[sortKey];
      if (x === null) return 1;
      if (y === null) return -1;
      return (x < y ? -1 : x > y ? 1 : 0) * dir;
    });
  });

  function sortBy(key: Key) {
    if (sortKey === key) ascending = !ascending;
    else {
      sortKey = key;
      ascending = true;
    }
  }

  function toggle(id: number, event: MouseEvent) {
    const next = new Set(event.shiftKey || event.ctrlKey || event.metaKey ? selection : []);
    if (next.has(id)) next.delete(id);
    else next.add(id);
    selection = next;
  }

  function mask(on: boolean) {
    if (!d || selection.size === 0) return;
    project.setMask(d.name, [...selection], on);
    selection = new Set();
  }

  const COLUMNS: { key: Key; letter: string; name: string; unit: () => string }[] = [
    { key: "id", letter: "", name: "#", unit: () => "" },
    { key: "t", letter: "A(X)", name: "T", unit: () => "K" },
    { key: "p", letter: "B(Y)", name: "p", unit: () => "MPa" },
    { key: "rho", letter: "C(Y)", name: "ρ", unit: () => "mol/L" },
    { key: "value", letter: "D(Y)", name: "", unit: () => unit.unit },
    { key: "u", letter: "E(yEr)", name: "U", unit: () => "%" },
    { key: "phase", letter: "F", name: "Phase", unit: () => "" },
  ];
</script>

<div class="view">
  {#if !d}
    <div class="empty well">Import data first; double-click a dataset in the project tree to open its worksheet.</div>
  {:else}
    <div class="bar row">
      <select class="field" value={d.name} onchange={(e) => project.openWorksheet((e.currentTarget as HTMLSelectElement).value)} aria-label="Dataset">
        {#each project.datasets as x (x.name)}<option value={x.name}>{x.name}</option>{/each}
      </select>
      <button class="btn" onclick={addColumn}>Add column</button>
      <button class="btn" onclick={() => mask(true)} disabled={selection.size === 0}>Mask selected</button>
      <button class="btn" onclick={() => mask(false)} disabled={selection.size === 0}>Unmask</button>
      <button class="btn" onclick={() => (selection = new Set(d.point_ids))}>Select all</button>
      <button class="btn" disabled title="ThermoML export: 0.2">Export ThermoML…</button>
      <span class="spacer"></span>
      <span class="muted">{d.values.length} rows · {masked.size} masked · {selection.size} selected</span>
    </div>
    <div class="formula row">
      {#if editing !== null}
        <input class="field name" bind:value={draft.name} aria-label="Column name" />
        <span class="fx">fx</span>
        <input class="field grow mono" bind:value={draft.formula} onkeydown={(e) => e.key === "Enter" && applyFormula()} aria-label="Formula" placeholder="e.g. y / eos('Dmass', T, p, fluid='{d.fluid}')" />
        <input class="field unit" bind:value={draft.unit} aria-label="Unit" placeholder="unit" />
        <button class="btn default" onclick={applyFormula}>Apply</button>
        <button class="btn" onclick={removeColumn}>Delete column</button>
        <button class="btn" onclick={() => (editing = null)}>Close</button>
      {:else}
        <span class="cellref">Filter</span>
        <input class="field grow mono" bind:value={filterDraft} onkeydown={(e) => e.key === "Enter" && applyFilter()} aria-label="Row filter" placeholder="e.g. T > 340 and p > 2e6   (columns: T p rho y U u u_rel and formula columns)" />
        <button class="btn" onclick={applyFilter}>Apply filter</button>
      {/if}
    </div>
    {#if formulaError}<div class="notice error">{formulaError}</div>{/if}
    <div class="well grid-wrap">
      <table class="grid sheet">
        <thead>
          <tr>
            {#each COLUMNS as c (c.key)}
              <th class="sortable" onclick={() => sortBy(c.key)}>
                <div class="letter">{c.letter}</div>
                <div>{c.key === "value" ? unit.symbol : c.name}{sortKey === c.key ? (ascending ? " ▲" : " ▼") : ""}</div>
              </th>
            {/each}
            {#each sheet.formulas as f, i (i)}
              <th class="formula-col" onclick={() => editColumn(i)} title="{f.name} = {f.formula}">
                <div class="letter">{String.fromCharCode(71 + i)}(Y) · fx</div>
                <div>{f.name}</div>
              </th>
            {/each}
          </tr>
          <tr class="units">{#each COLUMNS as c (c.key)}<td>{c.unit()}</td>{/each}{#each sheet.formulas as f, i (i)}<td>{f.unit}</td>{/each}</tr>
        </thead>
        <tbody>
          {#each rows as r (r.id)}
            <tr class:sel={selection.has(r.id)} class:masked={masked.has(r.id)} class:filtered={computed && computed.filter[position.get(r.id) ?? 0] === false} onclick={(e) => toggle(r.id, e)}>
              <td class="rowhead">{r.id + 1}</td>
              <td class="num">{fmt(r.t, 6)}</td>
              <td class="num">{r.p === null ? "" : fmt(r.p * 1e-6, 5)}</td>
              <td class="num">{r.rho === null ? "" : fmt(r.rho / 1000, 5)}</td>
              <td class="num value">{fmt(r.value * unit.factor, 6)}</td>
              <td class="num">{r.u === null ? "" : r.u.toFixed(2)}</td>
              <td>{r.phase}</td>
              {#each sheet.formulas as f (f.name)}
                <td class="num computed">{fmt(computed?.columns[f.name]?.[position.get(r.id) ?? 0] ?? null, 6)}</td>
              {/each}
            </tr>
          {/each}
        </tbody>
        {#if computed}
          <tfoot>
            {#each [["Mean", "mean"], ["SD", "std"], ["Min", "min"], ["Max", "max"], ["N", "n"]] as [label, key] (key)}
              <tr class="stats">
                <td class="rowhead">{label}</td>
                {#each [["T", 1], ["p", 1e-6], ["rho", 1e-3], ["y", unit.factor], ["U_pct", 1]] as [col, f] (col)}
                  <td class="num">{key === "n" ? computed.statistics[col]?.n : fmt(((computed.statistics[col]?.[key as keyof Stat] as number | null) ?? NaN) * (f as number), 5)}</td>
                {/each}
                <td></td>
                {#each sheet.formulas as fcol (fcol.name)}
                  <td class="num">{key === "n" ? computed.statistics[fcol.name]?.n : fmt((computed.statistics[fcol.name]?.[key as keyof Stat] as number | null) ?? null, 5)}</td>
                {/each}
              </tr>
            {/each}
          </tfoot>
        {/if}
      </table>
    </div>
    <p class="muted">
      Click to select, Shift/Ctrl-click for several. Masked rows are kept in the worksheet and shown in plots as excluded,
      but not used in fits, validation or consistency. Values are SI internally and converted only for display.
    </p>
  {/if}
</div>

<style>
  .view {
    display: flex;
    flex-direction: column;
    gap: 5px;
    height: 100%;
    min-height: 0;
  }
  .bar {
    flex-wrap: wrap;
  }
  .formula {
    gap: 4px;
  }
  .cellref,
  .fx {
    padding: 2px 6px;
    background: var(--field);
    border: 1px solid var(--shadow);
  }
  .fx {
    font-style: italic;
  }
  .grow {
    flex: 1;
  }
  .grid-wrap {
    flex: 1;
    min-height: 0;
    overflow: auto;
  }
  .sheet th {
    text-align: center;
    cursor: pointer;
  }
  .letter {
    font-size: 10px;
    color: var(--muted);
  }
  .sheet thead {
    position: sticky;
    top: 0;
    z-index: 2;
  }
  .sheet thead :global(th) {
    position: static;
  }
  .units td {
    font-family: var(--mono);
    background: #fbf7e3;
  }
  .rowhead {
    text-align: right;
    background: var(--face);
  }
  td.value {
    background: #dde5f3;
  }
  tr.masked td {
    color: var(--error);
    text-decoration: line-through;
    background: #f5c6c6;
  }
  tr.sel td {
    background: var(--select);
  }
  tr.filtered td {
    color: var(--muted);
    background: #eee;
  }
  td.computed {
    background: #eef6e8;
  }
  th.formula-col {
    cursor: pointer;
    background: #e3eed8;
  }
  .stats td {
    font-weight: 700;
    background: #fbf7e3;
  }
  .name {
    width: 110px;
  }
  .unit {
    width: 80px;
  }
  .error {
    color: var(--error);
  }
</style>
