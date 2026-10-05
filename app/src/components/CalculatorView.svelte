<script lang="ts">
  import { computeProperty, densityRequest, errorMessage, type PropertyResult } from "../lib/api";
  import { formatValue } from "../lib/units";

  let fluid = $state("R134a");
  let temperature = $state("300");
  let pressure = $state("1");
  let busy = $state(false);
  let result = $state<PropertyResult | null>(null);
  let error = $state<string | null>(null);

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

<div class="calc">
  <fieldset class="group">
    <legend>Property calculator</legend>
    <form onsubmit={calculate} aria-busy={busy}>
      <label for="c-fluid">Fluid</label>
      <input id="c-fluid" class="field" name="fluid" bind:value={fluid} autocomplete="off" spellcheck="false" />
      <label for="c-t">Temperature (K)</label>
      <input id="c-t" class="field num" name="temperature" bind:value={temperature} inputmode="decimal" />
      <label for="c-p">Pressure (MPa)</label>
      <input id="c-p" class="field num" name="pressure" bind:value={pressure} inputmode="decimal" />
      <span></span>
      <button class="btn default" type="submit" disabled={busy}>{busy ? "Calculating…" : "Calculate"}</button>
    </form>
    <section aria-live="polite">
      {#if result}
        <p class="result">
          <span class="muted">Density ρ</span>
          <output>{formatValue(result.value)}</output>
          <span class="muted">kg/m³</span>
        </p>
        <p class="muted">{result.backend} {result.backend_version}</p>
      {:else if error}
        <p class="error" role="alert">{error}</p>
      {/if}
    </section>
  </fieldset>
</div>

<style>
  .calc {
    max-width: 380px;
  }
  form {
    display: grid;
    grid-template-columns: auto 1fr;
    gap: 6px 10px;
    align-items: center;
  }
  .result {
    display: flex;
    align-items: baseline;
    gap: 8px;
    margin: 12px 0 2px;
  }
  output {
    font-family: var(--mono);
    font-size: 18px;
    font-weight: 700;
  }
</style>
