<script lang="ts">
  // Experiment view (design/mockups/16_Experiment): apparatus schematic with read-outs, repeats per state, replay of
  // the measurement campaign and the state map. The measurement planner (ranking new states) comes in 0.3.
  import type { Series } from "../lib/plot";
  import { project } from "../lib/project.svelte";
  import { display, fmt } from "../lib/quantities";
  import { measuredStates } from "../lib/study";
  import ScatterPlot from "./ScatterPlot.svelte";

  let datasetName = $state("");
  let stateIndex = $state(0);
  let repeat = $state(0);

  const d = $derived(project.datasets.find((x) => x.name === datasetName) ?? project.datasets.find((x) => x.pressure) ?? project.datasets[0]);
  const unit = $derived(display(d?.quantity ?? "viscosity"));
  const states = $derived(d ? measuredStates(d) : []);
  const cur = $derived(states[Math.min(stateIndex, Math.max(0, states.length - 1))]);
  const row = $derived(cur ? cur.rows[Math.min(repeat, cur.rows.length - 1)] : -1);
  const u = $derived(d?.expanded_uncertainty && row >= 0 ? (100 * d.expanded_uncertainty[row]) / d.values[row] : null);

  function step(delta: number) {
    if (!cur) return;
    let r = repeat + delta;
    let s = stateIndex;
    if (r >= cur.rows.length) {
      s = Math.min(states.length - 1, s + 1);
      r = s === stateIndex ? cur.rows.length - 1 : 0;
    } else if (r < 0) {
      s = Math.max(0, s - 1);
      r = s === stateIndex ? 0 : states[s].rows.length - 1;
    }
    stateIndex = s;
    repeat = r;
  }

  const map = $derived<Series[]>(
    project.datasets.filter((x) => x.pressure).map((x) => ({ name: x.name, x: x.temperature, y: (x.pressure ?? []).map((p) => p * 1e-6) })),
  );
</script>

<div class="exp">
  <div class="leftcol">
    <fieldset class="group">
      <legend>Apparatus: tandem capillary viscometer (schematic{d?.provenance?.citation ? `, ${d.provenance.citation}` : ""})</legend>
      <svg viewBox="0 0 700 300" class="schematic">
        <rect x="0" y="0" width="700" height="300" fill="#f8f7f2" />
        {#each [
          { x: 70, label: "Temperature T", value: cur ? `${fmt(d?.temperature[row], 5)} K` : "–" },
          { x: 230, label: "Pressure p", value: cur && d?.pressure ? `${fmt((d.pressure[row] ?? 0) * 1e-6, 4)} MPa` : "–" },
          { x: 390, label: "ΔP long / short", value: "[raw log]" },
          { x: 550, label: "Flow rate q (Coriolis)", value: "[raw log]" },
        ] as r (r.x)}
          <rect x={r.x} y="12" width="130" height="34" fill="#111" />
          <text x={r.x + 6} y="25" fill="#9fd" font-size="9">{r.label}</text>
          <text x={r.x + 6} y="41" fill="#6f6" font-size="13" font-family="monospace">{r.value}</text>
        {/each}
        <rect x="210" y="75" width="330" height="140" fill="none" stroke="#c0702a" stroke-dasharray="5 3" />
        <text x="218" y="90" fill="#c0702a" font-size="10">Thermostatted zone (heater C)</text>
        <rect x="245" y="120" width="110" height="24" fill="#dde5f3" stroke="#334" />
        <text x="300" y="136" text-anchor="middle" font-size="10">Long capillary</text>
        <rect x="390" y="120" width="110" height="24" fill="#dde5f3" stroke="#334" />
        <text x="445" y="136" text-anchor="middle" font-size="10">Short capillary</text>
        <path d="M120 132 H245 M355 132 H390 M500 132 H620 V170 M120 132 V240 H330 M430 240 H620 V210" fill="none" stroke="#000" />
        <rect x="575" y="170" width="90" height="38" fill="#e8e5dc" stroke="#334" />
        <text x="620" y="193" text-anchor="middle" font-size="10">Cooler J</text>
        <rect x="70" y="240" width="90" height="34" fill="#e8e5dc" stroke="#334" />
        <text x="115" y="261" text-anchor="middle" font-size="10">Syringe pump F</text>
        <rect x="330" y="225" width="100" height="30" fill="#e8e5dc" stroke="#334" />
        <text x="380" y="244" text-anchor="middle" font-size="10">Flowmeter G</text>
        <rect x="470" y="225" width="150" height="34" fill="#111" />
        <text x="476" y="238" fill="#9fd" font-size="9">{unit.label} {unit.symbol}</text>
        <text x="476" y="254" fill="#6f6" font-size="13" font-family="monospace">{cur ? `${fmt((d?.values[row] ?? 0) * unit.factor, 5)} ${unit.unit}` : "–"}</text>
      </svg>
    </fieldset>
    <div class="lower">
      <fieldset class="group">
        <legend>Repeats at this state{cur ? ` (${cur.phase || "–"}, ${fmt(cur.temperature, 4)} K${cur.pressure ? `, ${fmt(cur.pressure * 1e-6, 3)} MPa` : ""})` : ""}</legend>
        <table class="grid">
          <thead><tr><th>Repeat</th><th>T (K)</th><th>p (MPa)</th><th>{unit.symbol} ({unit.unit})</th></tr></thead>
          <tbody>
            {#each cur?.rows ?? [] as i, k (i)}
              <tr class:sel={i === row} class="clickable" onclick={() => (repeat = k)}>
                <td>{k + 1}</td><td class="num">{fmt(d?.temperature[i], 6)}</td><td class="num">{d?.pressure ? fmt(d.pressure[i] * 1e-6, 4) : ""}</td><td class="num">{fmt((d?.values[i] ?? 0) * unit.factor, 6)}</td>
              </tr>
            {/each}
          </tbody>
        </table>
        {#if cur}
          <p class="muted">Mean {fmt(cur.mean * unit.factor, 5)} {unit.unit} · spread {fmt(cur.spread * unit.factor, 3)} {unit.unit} ({((100 * cur.spread) / cur.mean).toFixed(2)} %){u !== null ? ` · stated U ${u.toFixed(2)} %` : ""}</p>
        {/if}
      </fieldset>
      <fieldset class="group">
        <legend>Measurement replay</legend>
        <div class="row">
          <select class="field" value={d?.name ?? ""} onchange={(e) => { datasetName = (e.currentTarget as HTMLSelectElement).value; stateIndex = 0; repeat = 0; }}>
            {#each project.datasets as x (x.name)}<option value={x.name}>{x.name}</option>{/each}
          </select>
          <button class="btn" onclick={() => { stateIndex = 0; repeat = 0; }} aria-label="First">|◀</button>
          <button class="btn" onclick={() => step(-1)} aria-label="Previous">◀</button>
          <button class="btn" onclick={() => step(1)} aria-label="Next">▶</button>
          <button class="btn" onclick={() => { stateIndex = states.length - 1; repeat = 0; }} aria-label="Last">▶|</button>
        </div>
        <p>State {states.length ? stateIndex + 1 : 0} of {states.length} · repeat {repeat + 1} of {cur?.rows.length ?? 0}</p>
        <div class="progress">
          {#each states as s, k (k)}
            <button class="cell" class:done={k < stateIndex} class:now={k === stateIndex} class:vap={s.phase.includes("vap") || s.phase.includes("gas")} onclick={() => { stateIndex = k; repeat = 0; }} aria-label="State {k + 1}"></button>
          {/each}
        </div>
      </fieldset>
    </div>
  </div>
  <aside class="planner">
    <fieldset class="group">
      <legend>State map</legend>
      {#if map.length}<ScatterPlot series={map} xLabel="T / K" yLabel="p / MPa" height={280} />{:else}<p class="muted">Import data with pressures.</p>{/if}
    </fieldset>
    <fieldset class="group">
      <legend>Suggested measurements</legend>
      <table class="props"><tbody>
        <tr><td>Liquid</td><td>[from planner run]</td></tr>
        <tr><td>Vapour</td><td>[from planner run]</td></tr>
        <tr><td>Expected gain</td><td>[from planner run]</td></tr>
      </tbody></table>
      <div class="row"><span class="muted">Measurement planning (expected reduction of model uncertainty): 0.3.</span><span class="spacer"></span><button class="btn" disabled>Run planner</button></div>
    </fieldset>
  </aside>
</div>

<style>
  .exp {
    display: grid;
    grid-template-columns: minmax(0, 1fr) 300px;
    gap: 6px;
    height: 100%;
    min-height: 0;
    overflow: auto;
  }
  .leftcol {
    display: grid;
    gap: 6px;
    align-content: start;
  }
  .schematic {
    width: 100%;
    height: auto;
  }
  .lower {
    display: grid;
    grid-template-columns: repeat(auto-fit, minmax(320px, 1fr));
    gap: 6px;
  }
  .progress {
    display: flex;
    gap: 2px;
    margin-top: 6px;
  }
  .cell {
    flex: 1;
    height: 14px;
    padding: 0;
    background: #fff;
    border: 1px solid var(--shadow);
  }
  .cell.done {
    background: #1f5fa8;
  }
  .cell.done.vap {
    background: #b5540a;
  }
  .cell.now {
    outline: 2px solid #000;
  }
  .planner {
    display: grid;
    gap: 6px;
    align-content: start;
  }
</style>
