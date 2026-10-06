<script lang="ts">
  import { errorMessage, worker } from "../lib/api";
  import {
    buildMapping,
    type ColumnChoice,
    guessColumn,
    ROLE_LABELS,
    ROLES,
    UNCERTAINTY_KINDS,
    UNITS,
  } from "../lib/mapping";
  import { project } from "../lib/project.svelte";
  import { display, QUANTITIES } from "../lib/quantities";
  import type { Preview } from "../lib/types";

  let step = $state<1 | 2>(1);
  let file = $state<File | null>(null);
  let quantity = $state("viscosity");
  let fluid = $state("");
  let name = $state("");
  let fluids = $state<string[]>([]);
  let preview = $state<Preview | null>(null);
  let sheet = $state<string | null>(null);
  let headerRow = $state(1);
  let coverage = $state(2);
  let choices = $state<ColumnChoice[]>([]);
  let error = $state<string | null>(null);
  let busy = $state(false);

  const headers = $derived(preview?.rows[headerRow - 1] ?? []);
  const dataRows = $derived(preview?.rows.slice(headerRow, headerRow + 8) ?? []);
  const isThermoML = $derived(preview?.thermoml ?? false);

  $effect(() => {
    worker<{ fluids: string[] }>("fluids")
      .then((r) => (fluids = r.fluids))
      .catch(() => (fluids = []));
  });

  function guessAll() {
    choices = headers.map((h) => guessColumn(h, quantity));
  }

  async function load(selected: File, chosenSheet: string | null = null) {
    error = null;
    busy = true;
    try {
      preview = await project.preview(selected, chosenSheet);
      sheet = preview.sheet;
      if (!name) name = selected.name.replace(/\.[^.]+$/, "");
      guessAll();
    } catch (err) {
      error = errorMessage(err);
      preview = null;
    } finally {
      busy = false;
    }
  }

  function picked(event: Event) {
    const input = event.currentTarget as HTMLInputElement;
    file = input.files?.[0] ?? null;
    preview = null;
    name = "";
    if (file) load(file);
  }

  function next() {
    error = null;
    if (!file || !preview) {
      error = "Choose a file.";
      return;
    }
    if (isThermoML) {
      finish();
      return;
    }
    if (!fluid.trim()) {
      error = "Enter the fluid of the data (as in the fluid library, e.g. R13I1 for CF3I).";
      return;
    }
    guessAll();
    step = 2;
  }

  async function finish() {
    if (!file) return;
    error = null;
    let mapping = null;
    if (!isThermoML) {
      try {
        mapping = buildMapping(headers, choices, quantity, headerRow, coverage, preview?.sheets.length ? sheet : null);
      } catch (err) {
        error = errorMessage(err);
        return;
      }
    }
    busy = true;
    const n = await project.importFile(file, mapping, isThermoML ? null : fluid.trim(), isThermoML ? null : name.trim() || null);
    busy = false;
    if (n !== null) project.importOpen = false;
    else error = project.status;
  }

  function close() {
    project.importOpen = false;
  }
</script>

<div class="backdrop" role="presentation">
  <div class="dialog" role="dialog" aria-modal="true" aria-labelledby="import-title">
    <header class="caption">
      <span id="import-title">Import Data – {step === 1 ? "Choose file" : "Map columns"}</span>
      <button class="x" onclick={close} aria-label="Close">×</button>
    </header>
    <nav class="steps">
      <span class:on={step === 1}>1. Choose file</span>
      <span class:on={step === 2}>2. Map columns</span>
      <span>3. Check data</span>
    </nav>

    <div class="content">
      {#if step === 1}
        <div class="grid1">
          <fieldset class="group">
            <legend>File</legend>
            <input type="file" accept=".csv,.txt,.tsv,.dat,.xlsx,.xlsm,.xml" onchange={picked} />
            <p class="muted">CSV/TXT, Excel (.xlsx) or ThermoML (.xml). The file is read by the worker; nothing is copied.</p>
            {#if preview && !isThermoML}
              <div class="well scroll">
                <table class="grid">
                  <tbody>
                    {#each preview.rows.slice(0, 10) as row, i (i)}
                      <tr><td class="muted">{i + 1}</td>{#each row as cell, j (j)}<td class="mono">{cell}</td>{/each}</tr>
                    {/each}
                  </tbody>
                </table>
              </div>
            {:else if isThermoML}
              <p class="ok">ThermoML file: fluids, properties, units and uncertainties are read from the file.</p>
            {/if}
          </fieldset>
          {#if !isThermoML}
            <fieldset class="group">
              <legend>What the file contains</legend>
              <div class="form">
                <label for="q">Property</label>
                <select id="q" class="field" bind:value={quantity}>
                  {#each QUANTITIES as q (q)}<option value={q}>{display(q).label}</option>{/each}
                </select>
                <label for="fl">Fluid</label>
                <input id="fl" class="field" list="fluid-list" bind:value={fluid} placeholder="e.g. R13I1" autocomplete="off" />
                <datalist id="fluid-list">
                  {#each fluids as f (f)}<option value={f}></option>{/each}
                </datalist>
                <label for="nm">Dataset name</label>
                <input id="nm" class="field" bind:value={name} />
              </div>
            </fieldset>
          {/if}
        </div>
      {:else if preview}
        <div class="row opts">
          <span>File: <b>{file?.name}</b></span>
          {#if preview.sheets.length}
            <label>
              sheet
              <select class="field" bind:value={sheet} onchange={() => file && load(file, sheet)}>
                {#each preview.sheets as s (s)}<option value={s}>{s}</option>{/each}
              </select>
            </label>
          {/if}
          <label>header row <input class="field num small" type="number" min="1" bind:value={headerRow} onchange={guessAll} /></label>
          <label>coverage factor k <input class="field num small" type="number" min="1" step="0.1" bind:value={coverage} /></label>
          <span class="spacer"></span>
          <button class="btn" onclick={guessAll}>Guess again</button>
        </div>
        <div class="well scroll map">
          <table class="grid">
            <thead>
              <tr>
                {#each headers as h, i (i)}
                  <th>
                    <div class="colhead">{h || `(column ${i + 1})`}</div>
                    {#if choices[i]}
                      <select class="field" bind:value={choices[i].role} aria-label="Role of {h}">
                        {#each ROLES as r (r)}<option value={r}>{ROLE_LABELS[r]}</option>{/each}
                      </select>
                      {#if choices[i].role === "uncertainty"}
                        <select class="field" bind:value={choices[i].uncertaintyKind} aria-label="Uncertainty kind of {h}">
                          {#each UNCERTAINTY_KINDS as u (u.kind)}<option value={u.kind}>{u.label}</option>{/each}
                        </select>
                      {:else if ["temperature", "pressure", "molar_density", "value"].includes(choices[i].role)}
                        {@const units = UNITS[choices[i].role === "value" ? quantity : choices[i].role] ?? []}
                        <select class="field" bind:value={choices[i].unit} aria-label="Unit of {h}">
                          {#each units as u (u)}<option value={u}>{u}</option>{/each}
                        </select>
                      {/if}
                    {/if}
                  </th>
                {/each}
              </tr>
            </thead>
            <tbody>
              {#each dataRows as row, r (r)}
                <tr>{#each headers as _, i (i)}<td class="mono">{row[i] ?? ""}</td>{/each}</tr>
              {/each}
            </tbody>
          </table>
        </div>
        <p class="muted">
          Preview of the first rows. Each column gets a role and a unit; values are converted to SI on import. Absolute
          uncertainties use the value's unit; the stated uncertainty is expanded with coverage factor k.
        </p>
      {/if}
      {#if error}<p class="error" role="alert">{error}</p>{/if}
    </div>

    <footer class="row buttons">
      <span class="spacer"></span>
      {#if step === 2}<button class="btn" onclick={() => (step = 1)}>&lt; Back</button>{/if}
      {#if step === 1}
        <button class="btn default" onclick={next} disabled={busy || !preview}>{isThermoML ? "Import" : "Next >"}</button>
      {:else}
        <button class="btn default" onclick={finish} disabled={busy}>{busy ? "Importing…" : "Import"}</button>
      {/if}
      <button class="btn" onclick={close}>Cancel</button>
    </footer>
  </div>
</div>

<style>
  .backdrop {
    position: fixed;
    inset: 0;
    z-index: 10;
    display: grid;
    place-items: center;
    background: rgba(0, 0, 0, 0.15);
  }
  .dialog {
    display: flex;
    flex-direction: column;
    width: min(980px, 96vw);
    height: min(620px, 92vh);
    background: var(--face);
    border: 1px solid;
    border-color: var(--hilite) var(--dark) var(--dark) var(--hilite);
    box-shadow: 2px 2px 0 var(--shadow);
  }
  .caption {
    display: flex;
    align-items: center;
    padding: 3px 4px 3px 8px;
    font-weight: 700;
    color: #fff;
    background: var(--navy);
  }
  .caption span {
    flex: 1;
  }
  .x {
    width: 16px;
    height: 14px;
    padding: 0;
    line-height: 10px;
    background: var(--face);
    border: 1px solid;
    border-color: var(--hilite) var(--dark) var(--dark) var(--hilite);
  }
  .steps {
    display: flex;
    gap: 2px;
    padding: 4px 12px;
    border-bottom: 1px solid var(--shadow);
  }
  .steps span {
    padding: 2px 10px;
  }
  .steps .on {
    font-weight: 700;
    color: #fff;
    background: var(--navy);
  }
  .content {
    display: flex;
    flex: 1;
    flex-direction: column;
    gap: 8px;
    min-height: 0;
    padding: 10px 12px;
  }
  .grid1 {
    display: grid;
    grid-template-columns: 1fr 300px;
    gap: 10px;
    min-height: 0;
  }
  .form {
    display: grid;
    grid-template-columns: auto 1fr;
    gap: 6px 8px;
    align-items: center;
  }
  .scroll {
    max-height: 340px;
    margin-top: 8px;
    overflow: auto;
  }
  .map {
    flex: 1;
    max-height: none;
  }
  .colhead {
    margin-bottom: 3px;
    font-weight: 700;
  }
  .map select {
    display: block;
    width: 130px;
    margin-top: 2px;
  }
  .opts label {
    display: flex;
    gap: 4px;
    align-items: center;
  }
  .small {
    width: 52px;
  }
  .buttons {
    padding: 8px 12px;
    border-top: 1px solid var(--shadow);
    box-shadow: inset 0 1px 0 var(--hilite);
  }
  .buttons .btn {
    min-width: 84px;
  }
</style>
