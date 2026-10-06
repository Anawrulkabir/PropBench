<script lang="ts">
  // Property calculator (design/mockups/21_Calculator): one state, several backends/models side by side with the
  // deviation from the chosen reference. All values are computed by the worker; units are converted for display.
  import { errorMessage, worker } from "../lib/api";
  import { project } from "../lib/project.svelte";
  import { fmt } from "../lib/quantities";

  interface BackendRow {
    id: string;
    label: string;
    status: "installed" | "component" | "not found";
    available: boolean;
  }
  const BACKENDS: BackendRow[] = [
    { id: "CoolProp::HEOS", label: "CoolProp · reference EoS (HEOS)", status: "installed", available: true },
    { id: "CoolProp::PR", label: "CoolProp · Peng–Robinson", status: "installed", available: true },
    { id: "CoolProp::SRK", label: "CoolProp · SRK", status: "installed", available: true },
    { id: "CoolProp::PCSAFT", label: "CoolProp · PC-SAFT", status: "installed", available: true },
    { id: "FeOs::PC-SAFT", label: "FeOs · PC-SAFT", status: "component", available: true },
    { id: "teqp", label: "teqp · cubic, SAFT, GERG-2008", status: "component", available: false },
    { id: "thermo", label: "thermo · cubic family, correlations", status: "component", available: false },
    { id: "REFPROP", label: "REFPROP 10 (your licence, via ctREFPROP)", status: "not found", available: false },
    { id: "TREND", label: "TREND (your licence)", status: "not found", available: false },
  ];
  // CoolProp output names; display factor from SI
  const PROPERTIES = [
    { output: "Dmass", label: "Density ρ", unit: "kg/m³", factor: 1, digits: 6 },
    { output: "Cpmass", label: "Heat capacity cp", unit: "J/(kg·K)", factor: 1, digits: 5 },
    { output: "Cvmass", label: "Heat capacity cv", unit: "J/(kg·K)", factor: 1, digits: 5 },
    { output: "speed_of_sound", label: "Speed of sound w", unit: "m/s", factor: 1, digits: 5 },
    { output: "Hmass", label: "Enthalpy h", unit: "kJ/kg", factor: 1e-3, digits: 6, referenceState: true },
    { output: "Smass", label: "Entropy s", unit: "kJ/(kg·K)", factor: 1e-3, digits: 5, referenceState: true },
    { output: "Z", label: "Compressibility factor Z", unit: "", factor: 1, digits: 5 },
    { output: "viscosity", label: "Viscosity η", unit: "µPa·s", factor: 1e6, digits: 5 },
    { output: "conductivity", label: "Thermal conductivity λ", unit: "mW/(m·K)", factor: 1e3, digits: 5 },
  ];
  const PAIRS = [
    { id: "PT_INPUTS", label: "T, p", a: { label: "T", unit: "K", factor: 1 }, b: { label: "p", unit: "MPa", factor: 1e6 }, order: "ba" },
    { id: "DmolarT_INPUTS", label: "T, ρ", a: { label: "T", unit: "K", factor: 1 }, b: { label: "ρ", unit: "mol/L", factor: 1e3 }, order: "ba" },
    { id: "QT_INPUTS", label: "T, saturation (Q)", a: { label: "T", unit: "K", factor: 1 }, b: { label: "Q", unit: "0 liquid … 1 vapour", factor: 1 }, order: "ba" },
  ];
  const PHASES: Record<number, string> = { 0: "liquid", 1: "supercritical", 2: "supercritical gas", 3: "supercritical liquid", 5: "gas", 6: "two-phase" };

  let fluid = $state("R134a");
  let pairId = $state("PT_INPUTS");
  let aText = $state("300");
  let bText = $state("1.0");
  let reference = $state("CoolProp::HEOS");
  let threshold = $state(5);
  let chosen = $state<Record<string, boolean>>({ "CoolProp::HEOS": true, "CoolProp::PR": true, "CoolProp::SRK": true, "CoolProp::PCSAFT": true });
  let fluids = $state<string[]>([]);
  let results = $state<Record<string, Record<string, number | null>>>({});
  let phase = $state("");
  let error = $state<string | null>(null);
  let busy = $state(false);
  let computedFor = $state("");

  const pair = $derived(PAIRS.find((p) => p.id === pairId) ?? PAIRS[0]);
  const columns = $derived(BACKENDS.filter((b) => b.available && chosen[b.id]));

  $effect(() => {
    worker<{ fluids: string[] }>("fluids").then((r) => (fluids = r.fluids)).catch(() => (fluids = []));
  });

  async function calculate(event?: SubmitEvent) {
    event?.preventDefault();
    error = null;
    const a = Number(aText.trim());
    const b = Number(bText.trim());
    if (!fluid.trim()) return void (error = "Enter a fluid, e.g. R134a.");
    if (!Number.isFinite(a) || a <= 0) return void (error = `${pair.a.label} must be a positive number in ${pair.a.unit}.`);
    if (!Number.isFinite(b) || b < 0) return void (error = `${pair.b.label} must be a number in ${pair.b.unit}.`);
    const v1 = b * pair.b.factor; // CoolProp pair order: second quantity first (p, T) / (ρ, T) / (Q, T)
    const v2 = a * pair.a.factor;
    busy = true;
    const out: Record<string, Record<string, number | null>> = {};
    try {
      for (const backend of columns) {
        out[backend.id] = {};
        for (const prop of PROPERTIES) {
          const r = await worker<{ outputs: Record<string, (number | null)[]> }>("properties", {
            fluid: fluid.trim(),
            pair: pair.id,
            values1: [v1],
            values2: [v2],
            outputs: [prop.output],
            backend: backend.id,
          }).catch(() => null);
          out[backend.id][prop.output] = r?.outputs[prop.output]?.[0] ?? null;
        }
      }
      const ph = await worker<{ outputs: Record<string, (number | null)[]> }>("properties", {
        fluid: fluid.trim(), pair: pair.id, values1: [v1], values2: [v2], outputs: ["Phase"],
      }).catch(() => null);
      const code = ph?.outputs.Phase?.[0];
      phase = code === null || code === undefined ? "" : (PHASES[Math.round(code)] ?? "");
      results = out;
      computedFor = `${fluid.trim()} at ${pair.a.label} = ${aText} ${pair.a.unit}, ${pair.b.label} = ${bText} ${pair.b.unit}`;
      if (Object.values(out["CoolProp::HEOS"] ?? {}).every((v) => v === null)) error = "The reference EoS could not compute this state.";
      project.note(`Calculated ${computedFor} with ${columns.length} backend models`);
    } catch (err) {
      error = errorMessage(err);
    } finally {
      busy = false;
    }
  }

  function deviation(id: string, output: string): number | null {
    // h and s depend on each backend's reference state: their differences are not model deviations
    if (PROPERTIES.find((p) => p.output === output)?.referenceState) return null;
    const v = results[id]?.[output];
    const r = results[reference]?.[output];
    if (v === null || v === undefined || r === null || r === undefined || r === 0 || id === reference) return null;
    return (100 * (v - r)) / r;
  }

  function tableText(): string {
    const head = ["Property", ...columns.map((c) => c.label)].join("\t");
    const body = PROPERTIES.map((p) =>
      [`${p.label} (${p.unit})`, ...columns.map((c) => { const v = results[c.id]?.[p.output]; return v === null || v === undefined ? "n/a" : String(v * p.factor); })].join("\t"),
    );
    return [head, ...body].join("\n");
  }
</script>

<div class="calc">
  <div class="top">
    <fieldset class="group">
      <legend>State</legend>
      <form onsubmit={calculate} aria-busy={busy}>
        <label for="c-fluid">Fluid</label>
        <input id="c-fluid" class="field" name="fluid" list="calc-fluids" bind:value={fluid} autocomplete="off" spellcheck="false" />
        <datalist id="calc-fluids">{#each fluids as f (f)}<option value={f}></option>{/each}</datalist>
        <label for="c-pair">Input pair</label>
        <select id="c-pair" class="field" bind:value={pairId}>{#each PAIRS as p (p.id)}<option value={p.id}>{p.label}</option>{/each}</select>
        <label for="c-a">{pair.a.label} ({pair.a.unit})</label>
        <input id="c-a" class="field num" name="temperature" bind:value={aText} inputmode="decimal" />
        <label for="c-b">{pair.b.label} ({pair.b.unit})</label>
        <input id="c-b" class="field num" name="pressure" bind:value={bText} inputmode="decimal" />
        <span>Phase</span>
        <span class="mono">{phase || "–"}</span>
        <span></span>
        <button class="btn default" type="submit" disabled={busy || columns.length === 0}>{busy ? "Calculating…" : "Calculate"}</button>
      </form>
    </fieldset>

    <fieldset class="group">
      <legend>Backends and models to compare</legend>
      {#each BACKENDS as b (b.id)}
        <label class="row line">
          <input type="checkbox" bind:checked={chosen[b.id]} disabled={!b.available} />
          <span class:muted={!b.available}>{b.label}</span>
          <span class="spacer"></span>
          <span class:ok={b.status === "installed"} class:link={b.status === "component"} class:error={b.status === "not found"}>{b.status}</span>
        </label>
      {/each}
      <div class="row opts">
        <label class="row">Reference
          <select class="field" bind:value={reference}>{#each columns as c (c.id)}<option value={c.id}>{c.label}</option>{/each}</select>
        </label>
        <label class="row">highlight above <input class="field num small" type="number" min="0" bind:value={threshold} /> %</label>
      </div>
    </fieldset>
  </div>

  {#if error}<p class="error" role="alert">{error}</p>{/if}

  {#if computedFor}
    <fieldset class="group">
      <legend>Results: {computedFor} (deviation from the reference in brackets)</legend>
      <div class="well scroll">
        <table class="grid">
          <thead><tr><th>Property</th>{#each columns as c (c.id)}<th class:refcol={c.id === reference}>{c.label.replace("CoolProp · ", "")}</th>{/each}</tr></thead>
          <tbody>
            {#each PROPERTIES as p (p.output)}
              <tr>
                <td>{p.label}{p.unit ? ` (${p.unit})` : ""}</td>
                {#each columns as c (c.id)}
                  {@const v = results[c.id]?.[p.output]}
                  {@const d = deviation(c.id, p.output)}
                  <td class="num" class:refcol={c.id === reference} class:error={d !== null && Math.abs(d) > threshold}>
                    {#if v === null || v === undefined}<span class="muted">n/a</span>{:else}
                      <output class:acceptance={p.output === "Dmass" && c.id === "CoolProp::HEOS"}>{p.output === "Dmass" ? (v * p.factor).toFixed(2) : fmt(v * p.factor, p.digits)}</output>
                      {#if d !== null}<span> ({d >= 0 ? "+" : ""}{d.toFixed(2)} %)</span>{/if}
                    {/if}
                  </td>
                {/each}
              </tr>
            {/each}
          </tbody>
        </table>
      </div>
      <div class="row">
        <span class="muted">n/a: the backend does not provide this property for this model. h and s: no deviation (backend reference states differ).</span>
        <span class="spacer"></span>
        <button class="btn" onclick={() => navigator.clipboard?.writeText(tableText())}>Copy table</button>
        <button class="btn" disabled title="Worksheets with formula columns: M3a">Send to worksheet</button>
        <button class="btn" onclick={() => project.open("graph")}>Plot in graph studio</button>
      </div>
    </fieldset>
  {/if}
</div>

<style>
  .calc {
    display: grid;
    gap: 8px;
    align-content: start;
    height: 100%;
    overflow: auto;
  }
  .top {
    display: grid;
    grid-template-columns: minmax(260px, 1fr) minmax(0, 1.4fr);
    gap: 8px;
  }
  form {
    display: grid;
    grid-template-columns: auto 1fr;
    gap: 6px 10px;
    align-items: center;
  }
  .line {
    min-height: 19px;
  }
  .opts {
    flex-wrap: wrap;
    margin-top: 6px;
  }
  .small {
    width: 48px;
  }
  .link {
    color: var(--navy);
  }
  .scroll {
    overflow-x: auto;
  }
  td.refcol,
  th.refcol {
    background: #e3eedd;
  }
  output.acceptance {
    font-weight: 700;
  }
</style>
