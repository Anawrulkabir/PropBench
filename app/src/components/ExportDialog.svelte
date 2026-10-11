<script lang="ts">
  // Export to CoolProp (README M4): a CoolProp fluid file holding a fitted ECS viscosity model, verified inside
  // CoolProp at the project's states before it is offered for download.
  import { errorMessage, worker } from "../lib/api";
  import { project } from "../lib/project.svelte";
  import DialogFrame from "./DialogFrame.svelte";

  interface Verification {
    fluid: string;
    max_rel_diff: number;
    identical: boolean;
    propbench: number[];
    coolprop: number[];
  }

  const exportable = $derived(project.candidates.filter((c) => c.fit && c.fit.model.kind === "ecs_viscosity"));
  let picked = $state(project.candidates.find((c) => c.fit && c.fit.model.kind === "ecs_viscosity")?.id ?? "");
  let name = $state(`${project.datasets[0]?.fluid ?? "fluid"}-PropBench`);
  let result = $state<{ json: string; verification: Verification } | null>(null);
  let error = $state("");
  let busy = $state(false);

  async function run() {
    const c = exportable.find((x) => x.id === picked);
    if (!c?.fit) return;
    busy = true;
    error = "";
    result = null;
    try {
      const r = await worker<{ json: string; verification: Verification }>("model.export_coolprop", { model: c.fit.model, name, datasets: project.activeDatasets() });
      result = r;
      project.note(`CoolProp export of ${c.label}: max. relative difference ${r.verification.max_rel_diff.toExponential(1)} at ${r.verification.propbench.length} states`);
    } catch (err) {
      error = errorMessage(err);
    } finally {
      busy = false;
    }
  }

  function download() {
    if (!result) return;
    const url = URL.createObjectURL(new Blob([result.json], { type: "application/json" }));
    const a = document.createElement("a");
    a.href = url;
    a.download = `${name}.json`;
    a.click();
    setTimeout(() => URL.revokeObjectURL(url), 1000);
    project.audit("export", `CoolProp fluid ${name}`);
  }

  const close = () => (project.dialog = null);
</script>

<DialogFrame title="Export to CoolProp" width="620px" height="440px" onclose={close}>
  {#if !exportable.length}
    <p>Fit an ECS viscosity model first: CoolProp evaluates ECS models (Huber et al. 2003) with its own equations of state. Models CoolProp cannot represent are never approximated.</p>
  {:else}
    <div class="form">
      <label for="x-model">Model</label>
      <select id="x-model" class="field" bind:value={picked}>{#each exportable as c (c.id)}<option value={c.id}>{c.label}</option>{/each}</select>
      <label for="x-name">Fluid name</label><input id="x-name" class="field" bind:value={name} />
    </div>
    {#if result}
      <fieldset class="group">
        <legend>Verified inside CoolProp</legend>
        <p class:ok={result.verification.identical} class:bad={!result.verification.identical}>
          {result.verification.identical ? "Identical" : "Different"}: largest relative difference {result.verification.max_rel_diff.toExponential(2)} over {result.verification.propbench.length} states of the project.
        </p>
        <pre class="mono use">import CoolProp.CoolProp as CP
CP.add_fluids_as_JSON("HEOS", open("{name}.json").read())
CP.PropsSI("V", "T", 300, "Dmolar", 8000, "{result.verification.fluid}")</pre>
      </fieldset>
    {/if}
    {#if error}<div class="notice bad">{error}</div>{/if}
  {/if}
  {#snippet footer()}
    <span class="spacer"></span>
    <button class="btn" onclick={run} disabled={busy || !exportable.length}>{busy ? "Verifying…" : "Export and verify"}</button>
    <button class="btn default" onclick={download} disabled={!result?.verification.identical}>Save fluid file…</button>
    <button class="btn" onclick={close}>Close</button>
  {/snippet}
</DialogFrame>

<style>
  .form {
    display: grid;
    grid-template-columns: auto 1fr;
    gap: 5px 8px;
    align-items: center;
    margin-bottom: 8px;
  }
  .ok {
    color: var(--ok);
    font-weight: 700;
  }
  .bad {
    color: var(--error);
  }
  .use {
    padding: 6px;
    font-size: 11px;
    background: var(--field);
  }
</style>
