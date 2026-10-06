<script lang="ts">
  // Guided CF3I tutorial: one panel with every step, its explanation and a button that does it.
  import { project } from "../lib/project.svelte";
  import { currentStep, STEPS } from "../lib/tutorial";

  const state = $derived({
    datasets: project.datasets,
    checks: project.checks,
    consistency: project.consistency,
    candidates: project.candidates,
    locked: project.locked,
    comparison: project.comparison,
    log: project.log,
    filePath: project.filePath,
  });
  const current = $derived(currentStep(state));

  async function act(id: string) {
    switch (id) {
      case "data":
        await project.loadExample();
        project.open("data");
        break;
      case "check":
        project.open("data");
        await project.checkData();
        break;
      case "consistency":
        project.open("consistency");
        await project.analyzeConsistency();
        break;
      case "model":
        await project.loadKinds();
        await project.addCandidate("ecs_viscosity", "R134a");
        project.open("fit");
        break;
      case "fit": {
        const c = project.candidates.find((x) => x.start.kind === "ecs_viscosity") ?? project.candidates[0];
        if (c) {
          project.selected = { type: "candidate", id: c.id };
          project.open("fitting");
          await project.fit(c.id);
        }
        break;
      }
      case "validate":
        project.settings.methods = ["lostate"];
        project.rule.validation = "lostate";
        project.open("study");
        await project.runStudy();
        break;
      case "compare":
        await project.compareModels();
        project.open("results");
        break;
      case "figure":
        project.open("graph");
        break;
      case "save":
        await project.saveProject();
        break;
    }
  }
</script>

<aside class="tutorial" aria-label="CF3I tutorial">
  <header class="titlebar row">
    <span>CF3I tutorial · step {Math.min(current + 1, STEPS.length)} of {STEPS.length}</span>
    <span class="spacer"></span>
    <button class="close" onclick={() => (project.tutorial = false)} aria-label="Close the tutorial">×</button>
  </header>
  <ol>
    {#each STEPS as step, i (step.id)}
      {@const done = step.done(state)}
      <li class:done class:now={i === current}>
        <div class="title">{done ? "✓" : i + 1 + "."} {step.title}</div>
        {#if i === current}
          <p>{step.text}</p>
          <button class="btn default" onclick={() => act(step.id)} disabled={!!project.busy}>{step.action}</button>
        {/if}
      </li>
    {/each}
  </ol>
  {#if current === STEPS.length}<p class="finished">All steps done: you went from published data to a validated, compared model and a saved project.</p>{/if}
</aside>

<style>
  .tutorial {
    position: absolute;
    right: 8px;
    bottom: 34px;
    z-index: 30;
    width: 320px;
    max-height: 70%;
    overflow: auto;
    background: var(--face);
    border: 2px solid;
    border-color: var(--hilite) var(--dark) var(--dark) var(--hilite);
    box-shadow: 3px 3px 0 rgba(0, 0, 0, 0.3);
  }
  .titlebar {
    padding: 3px 6px;
    font-weight: 700;
    color: #fff;
    background: var(--navy);
  }
  .close {
    padding: 0 6px;
    color: #fff;
    background: none;
    border: none;
  }
  ol {
    margin: 0;
    padding: 6px 8px 6px 8px;
    list-style: none;
  }
  li {
    padding: 4px 2px;
    border-bottom: 1px solid var(--shadow);
  }
  li.done .title {
    color: var(--ok);
  }
  li.now {
    background: #fffbe6;
  }
  .title {
    font-weight: 700;
  }
  p {
    margin: 4px 0 6px;
    line-height: 1.4;
  }
  .finished {
    padding: 6px 8px;
    color: var(--ok);
    font-weight: 700;
  }
</style>
