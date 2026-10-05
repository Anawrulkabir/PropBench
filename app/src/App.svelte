<script lang="ts">
  import { computeProperty, densityRequest, errorMessage, type PropertyResult } from "./lib/api";
  import { formatValue } from "./lib/units";

  let fluid = $state("R134a");
  let temperature = $state("300");
  let pressure = $state("1");
  let busy = $state(false);
  let result: PropertyResult | null = $state(null);
  let error: string | null = $state(null);

  async function calculate(event: SubmitEvent) {
    event.preventDefault();
    result = null;
    error = null;
    const form = densityRequest(fluid, temperature, pressure);
    if (!form.ok) {
      error = form.error;
      return;
    }
    busy = true;
    try {
      result = await computeProperty(form.request);
    } catch (err) {
      error = errorMessage(err);
    } finally {
      busy = false;
    }
  }
</script>

<main>
  <h1>Property calculator</h1>
  <form onsubmit={calculate} aria-busy={busy}>
    <label>
      Fluid
      <input name="fluid" bind:value={fluid} autocomplete="off" spellcheck="false" />
    </label>
    <label>
      Temperature <span class="unit">K</span>
      <input name="temperature" bind:value={temperature} inputmode="decimal" />
    </label>
    <label>
      Pressure <span class="unit">MPa</span>
      <input name="pressure" bind:value={pressure} inputmode="decimal" />
    </label>
    <button type="submit" disabled={busy}>{busy ? "Calculating…" : "Calculate"}</button>
  </form>

  <section aria-live="polite">
    {#if result}
      <p class="result">
        <span class="label">Density ρ</span>
        <output>{formatValue(result.value)}</output>
        <span class="unit">kg/m³</span>
      </p>
      <p class="meta">{result.backend} {result.backend_version}</p>
    {:else if error}
      <p class="error" role="alert">{error}</p>
    {/if}
  </section>
</main>

<style>
  main {
    max-width: 28rem;
    margin: 2.5rem auto;
    padding: 0 1rem;
  }
  h1 {
    font-size: 1.35rem;
    font-weight: 600;
    margin: 0 0 1.25rem;
  }
  form {
    display: grid;
    gap: 0.85rem;
    padding: 1.25rem;
    background: var(--surface);
    border: 1px solid var(--border);
    border-radius: 8px;
  }
  label {
    display: grid;
    gap: 0.3rem;
    font-weight: 500;
  }
  input {
    font: inherit;
    padding: 0.45rem 0.6rem;
    color: var(--text);
    background: var(--bg);
    border: 1px solid var(--border);
    border-radius: 6px;
  }
  input:focus-visible,
  button:focus-visible {
    outline: 2px solid var(--accent);
    outline-offset: 1px;
  }
  button {
    font: inherit;
    font-weight: 600;
    padding: 0.55rem;
    color: var(--accent-text);
    background: var(--accent);
    border: none;
    border-radius: 6px;
    cursor: pointer;
  }
  button:disabled {
    opacity: 0.6;
    cursor: progress;
  }
  .unit,
  .meta,
  .label {
    color: var(--muted);
    font-weight: 400;
  }
  .result {
    display: flex;
    align-items: baseline;
    gap: 0.5rem;
    margin: 1.25rem 0 0.25rem;
  }
  output {
    font-size: 1.6rem;
    font-weight: 600;
    font-variant-numeric: tabular-nums;
  }
  .meta {
    margin: 0;
    font-size: 0.85rem;
  }
  .error {
    color: var(--error);
    margin-top: 1.25rem;
  }
</style>
