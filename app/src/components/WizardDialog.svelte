<script lang="ts">
  // New project wizard (design/mockups/03_Welcome): pick a task; the wizard opens the matching workflow.
  import { project } from "../lib/project.svelte";
  import DialogFrame from "./DialogFrame.svelte";

  const TASKS = [
    { id: "lookup", label: "Look up properties of a fluid", hint: "Pure fluids and mixtures: tables, plots, single points" },
    { id: "explore", label: "Explore experimental data", hint: "Browse published measurements and compare with models" },
    { id: "consistency", label: "Check data consistency", hint: "Find where datasets overlap and whether they agree" },
    { id: "fit", label: "Fit a model to my measurements", hint: "ECS, entropy scaling or PC-SAFT, also for a new fluid" },
    { id: "validate", label: "Validate and compare models", hint: "Unseen states, physics checks, uncertainty bands" },
    { id: "mixture", label: "Work with a mixture", hint: "Predict mixture properties, fit binary parameters (planned for 2.0)", disabled: true },
    { id: "tutorial", label: "Open the CF3I tutorial", hint: "Published CF3I viscosity data (Tuhin et al. 2024, Duan et al. 1999), from data to validated model" },
  ];
  const STEPS = ["Choose a task", "Select fluids", "Data sources", "Components", "Finish"];
  const NEEDS: Record<string, { name: string; state: "installed" | "download" | "planned" }[]> = {
    lookup: [{ name: "Core and calculator", state: "installed" }, { name: "CoolProp fluid library", state: "installed" }],
    explore: [{ name: "Core and calculator", state: "installed" }, { name: "Importers (CSV, Excel, ThermoML)", state: "installed" }, { name: "Experimental data: ThermoML archive", state: "planned" }],
    consistency: [{ name: "Consistency tools", state: "installed" }, { name: "NIST reference transport models (NISTIR 8209)", state: "installed" }],
    fit: [{ name: "Fitting and validation tools", state: "installed" }, { name: "CoolProp fluid library", state: "installed" }, { name: "NIST reference transport models", state: "installed" }],
    validate: [{ name: "Fitting and validation tools", state: "installed" }, { name: "NIST reference transport models", state: "installed" }],
    mixture: [{ name: "Mixture toolkit", state: "planned" }],
    tutorial: [{ name: "Core and calculator", state: "installed" }, { name: "Fitting and validation tools", state: "installed" }, { name: "NIST reference transport models", state: "installed" }],
  };

  let task = $state("tutorial");
  let step = $state(0);
  let fluid = $state("R13I1");
  const needs = $derived(NEEDS[task] ?? []);

  function close() {
    project.dialog = null;
  }
  async function finish() {
    close();
    if (task === "lookup") project.open("calculator");
    else if (task === "tutorial") {
      await project.loadExample();
      project.open("data");
    } else {
      project.importOpen = true;
      if (task === "consistency") project.view = "consistency";
      if (task === "fit") project.view = "fit";
      if (task === "validate") project.view = "study";
    }
  }
</script>

<DialogFrame title="New Project Wizard" width="900px" height="600px" onclose={close}>
  <div class="wizard">
    <aside class="side">
      <h2>New project</h2>
      {#each STEPS as s, i (s)}
        <div class="step" class:on={i === step}><span class="num">{i + 1}</span>{s}</div>
      {/each}
      <p class="hint">Only the components a task needs are used. You can add or remove them later in Tools › Components.</p>
    </aside>
    <section class="main">
      {#if step === 0}
        <b>What would you like to do?</b>
        <div class="well tasks">
          {#each TASKS as t (t.id)}
            <label class="task" class:sel={task === t.id} class:off={t.disabled}>
              <input type="radio" name="task" value={t.id} bind:group={task} disabled={t.disabled} />
              <span><span class="t">{t.label}</span><span class="h">{t.hint}</span></span>
            </label>
          {/each}
        </div>
      {:else if step === 1}
        <b>Which fluid?</b>
        <div class="form"><label for="wz-fluid">Fluid</label><input id="wz-fluid" class="field" bind:value={fluid} disabled={task === "tutorial"} /></div>
        <p class="muted">The fluid is identified by name, alias or CAS number when data are imported (e.g. R13I1 for CF3I).</p>
      {:else if step === 2}
        <b>Data sources</b>
        <p>{task === "tutorial" ? "Published tables of Tuhin et al. (2024) and Duan et al. (1999), with their DOIs." : "Your own files (CSV, Excel, ThermoML XML) are imported in the next window."}</p>
      {:else if step === 3}
        <b>Components this task needs</b>
      {:else}
        <b>Ready</b>
        <p>{TASKS.find((t) => t.id === task)?.label}. Click Finish to start.</p>
      {/if}
      <fieldset class="group">
        <legend>Components this task needs</legend>
        <table class="grid">
          <tbody>
            {#each needs as n (n.name)}
              <tr>
                <td style="width: 20px">{n.state === "installed" ? "✓" : "↓"}</td>
                <td>{n.name}</td>
                <td class:ok={n.state === "installed"} class:muted={n.state !== "installed"}>
                  {n.state === "installed" ? "installed" : n.state === "download" ? "will be downloaded" : "planned"}
                </td>
              </tr>
            {/each}
          </tbody>
        </table>
      </fieldset>
    </section>
  </div>
  {#snippet footer()}
    <button class="btn" disabled title="Documentation: M5">Help</button>
    <span class="spacer"></span>
    <button class="btn" onclick={() => (step = Math.max(0, step - 1))} disabled={step === 0}>&lt; Back</button>
    {#if step < STEPS.length - 1}
      <button class="btn default" onclick={() => (step += 1)}>Next &gt;</button>
    {:else}
      <button class="btn default" onclick={finish}>Finish</button>
    {/if}
    <button class="btn" onclick={close}>Cancel</button>
  {/snippet}
</DialogFrame>

<style>
  .wizard {
    display: grid;
    grid-template-columns: 210px 1fr;
    gap: 0;
    height: 100%;
    margin: -10px -12px;
  }
  .side {
    display: flex;
    flex-direction: column;
    gap: 6px;
    padding: 12px;
    color: #dfe6f5;
    background: #1f3c7a;
  }
  .side h2 {
    margin: 0 0 10px;
    font-size: 15px;
    color: #fff;
  }
  .step {
    display: flex;
    gap: 8px;
    align-items: center;
  }
  .step.on {
    font-weight: 700;
    color: #fff;
  }
  .num {
    display: grid;
    place-items: center;
    width: 18px;
    height: 18px;
    font-size: 10px;
    border: 1px solid #dfe6f5;
    border-radius: 50%;
  }
  .step.on .num {
    color: #1f3c7a;
    background: #fff;
  }
  .hint {
    margin-top: auto;
    line-height: 1.5;
  }
  .main {
    display: grid;
    gap: 8px;
    align-content: start;
    padding: 12px;
    overflow: auto;
  }
  .tasks {
    display: grid;
  }
  .task {
    display: flex;
    gap: 8px;
    align-items: flex-start;
    padding: 5px 8px;
  }
  .task.sel {
    background: #e6e2d6;
  }
  .task.off {
    color: var(--shadow);
  }
  .t {
    display: block;
  }
  .h {
    display: block;
    color: var(--muted);
  }
  .form {
    display: grid;
    grid-template-columns: auto 220px;
    gap: 6px;
    align-items: center;
  }
</style>
