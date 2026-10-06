<script lang="ts">
  // Worksheet (design/mockups/12_Worksheet): one dataset as a table with a units row; masked rows stay in the
  // worksheet, struck through, and are left out of fits, validation and consistency.
  import { project } from "../lib/project.svelte";
  import { display, fmt } from "../lib/quantities";

  type Key = "id" | "t" | "p" | "rho" | "value" | "u" | "phase";
  let sortKey = $state<Key>("id");
  let ascending = $state(true);
  let selection = $state<Set<number>>(new Set());

  const d = $derived(project.datasets.find((x) => x.name === project.worksheet) ?? project.datasets[0]);
  const unit = $derived(display(d?.quantity ?? "viscosity"));
  const masked = $derived(new Set(d ? (project.masks[d.name] ?? []) : []));

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
      <button class="btn" disabled title="Formula columns: M3a">Add column</button>
      <button class="btn" disabled title="Formula columns: M3a">Set formula…</button>
      <button class="btn" onclick={() => mask(true)} disabled={selection.size === 0}>Mask selected</button>
      <button class="btn" onclick={() => mask(false)} disabled={selection.size === 0}>Unmask</button>
      <button class="btn" onclick={() => (selection = new Set(d.point_ids))}>Select all</button>
      <button class="btn" disabled title="ThermoML export: 0.2">Export ThermoML…</button>
      <span class="spacer"></span>
      <span class="muted">{d.values.length} rows · {masked.size} masked · {selection.size} selected</span>
    </div>
    <div class="formula row">
      <span class="cellref">{COLUMNS[4].letter.split("(")[0]}</span>
      <span class="fx">fx</span>
      <input class="field grow" disabled value="{unit.symbol} = measured value, SI {unit.unit === 'µPa·s' ? 'Pa·s' : ''} × {unit.factor}" />
    </div>
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
          </tr>
          <tr class="units">{#each COLUMNS as c (c.key)}<td>{c.unit()}</td>{/each}</tr>
        </thead>
        <tbody>
          {#each rows as r (r.id)}
            <tr class:sel={selection.has(r.id)} class:masked={masked.has(r.id)} onclick={(e) => toggle(r.id, e)}>
              <td class="rowhead">{r.id + 1}</td>
              <td class="num">{fmt(r.t, 6)}</td>
              <td class="num">{r.p === null ? "" : fmt(r.p * 1e-6, 5)}</td>
              <td class="num">{r.rho === null ? "" : fmt(r.rho / 1000, 5)}</td>
              <td class="num value">{fmt(r.value * unit.factor, 6)}</td>
              <td class="num">{r.u === null ? "" : r.u.toFixed(2)}</td>
              <td>{r.phase}</td>
            </tr>
          {/each}
        </tbody>
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
</style>
