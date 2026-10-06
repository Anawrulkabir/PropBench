<script lang="ts">
  // Main window (design/mockups/01_Main): toolbar, project tree, tabbed work area, properties, output, status bar.
  // The UI never computes: every action goes through the worker (lib/project.svelte.ts → Tauri → pb-engine).
  import CalculatorView from "./components/CalculatorView.svelte";
  import ConsistencyView from "./components/ConsistencyView.svelte";
  import DataView from "./components/DataView.svelte";
  import FitView from "./components/FitView.svelte";
  import ImportDialog from "./components/ImportDialog.svelte";
  import OutputPanel from "./components/OutputPanel.svelte";
  import ProjectTree from "./components/ProjectTree.svelte";
  import PropertiesPanel from "./components/PropertiesPanel.svelte";
  import ResultsView from "./components/ResultsView.svelte";
  import StudyView from "./components/StudyView.svelte";
  import { project, type View } from "./lib/project.svelte";

  const TABS: { id: View; label: string }[] = [
    { id: "data", label: "Data check" },
    { id: "consistency", label: "Data consistency" },
    { id: "fit", label: "Fit" },
    { id: "study", label: "Study setup" },
    { id: "results", label: "Results" },
    { id: "calculator", label: "Calculator" },
  ];

  const hasData = $derived(project.datasets.length > 0);
  const hasModels = $derived(project.candidates.length > 0);

  function fitSelected() {
    project.view = "fit";
    const id = project.selected?.type === "candidate" ? project.selected.id : project.candidates[0]?.id;
    if (id) project.fit(id);
  }
</script>

<div class="window">
  <div class="toolbar row">
    <button class="tool btn" onclick={() => (project.importOpen = true)} disabled={!!project.busy}>
      <span class="ico">⤓</span>Import
    </button>
    <button class="tool btn" onclick={() => project.checkData()} disabled={!!project.busy || !hasData}>
      <span class="ico">✓</span>Check
    </button>
    <button
      class="tool btn"
      onclick={() => {
        project.view = "consistency";
        project.analyzeConsistency();
      }}
      disabled={!!project.busy || !hasData}
    >
      <span class="ico">≈</span>Consistency
    </button>
    <span class="sep"></span>
    <button class="tool btn" onclick={fitSelected} disabled={!!project.busy || !hasModels}>
      <span class="ico">⟋</span>Fit
    </button>
    <button
      class="tool btn primary"
      onclick={() => {
        project.view = "study";
        project.runStudy();
      }}
      disabled={!!project.busy || !hasModels}
    >
      <span class="ico">▷</span>Validate
    </button>
    <span class="sep"></span>
    <button class="tool btn" onclick={() => (project.view = "results")}><span class="ico">▤</span>Results</button>
    <span class="spacer"></span>
    <label class="row backend">
      Backend:
      <select class="field" aria-label="Backend"><option>CoolProp – reference EoS</option></select>
    </label>
  </div>

  <div class="main">
    <section class="pane left">
      <header class="titlebar">Project</header>
      <ProjectTree />
    </section>

    <section class="center">
      <div class="tabs" role="tablist">
        {#each TABS as t (t.id)}
          <button class="tab" class:on={project.view === t.id} role="tab" aria-selected={project.view === t.id} onclick={() => (project.view = t.id)}>
            {t.label}
          </button>
        {/each}
      </div>
      <div class="work">
        {#if project.view === "data"}<DataView />
        {:else if project.view === "consistency"}<ConsistencyView />
        {:else if project.view === "fit"}<FitView />
        {:else if project.view === "study"}<StudyView />
        {:else if project.view === "results"}<ResultsView />
        {:else}<CalculatorView />{/if}
      </div>
      <div class="output"><OutputPanel /></div>
    </section>

    <section class="pane right"><PropertiesPanel /></section>
  </div>

  <footer class="status row">
    <span class="cell grow">{project.busy ? `${project.busy}…` : project.status}</span>
    <span class="cell">Selection rule: {project.locked ? "locked" : "open"}</span>
    <span class="cell">Seed {project.settings.seed}</span>
    <span class="cell">{project.datasets.length} datasets · {project.candidates.length} models</span>
    <span class="cell progress" class:running={!!project.busy} aria-hidden="true"></span>
  </footer>
</div>

{#if project.importOpen}<ImportDialog />{/if}

<style>
  .window {
    display: grid;
    grid-template-rows: auto 1fr auto;
    height: 100%;
  }
  .toolbar {
    gap: 2px;
    padding: 3px 6px;
    border-bottom: 1px solid var(--shadow);
    box-shadow: 0 1px 0 var(--hilite);
  }
  .tool {
    display: flex;
    flex-direction: column;
    align-items: center;
    min-width: 54px;
    padding: 2px 6px;
  }
  .tool.primary:not(:disabled) {
    background: #c9d8c6;
  }
  .ico {
    font-size: 13px;
    line-height: 15px;
  }
  .sep {
    width: 2px;
    height: 36px;
    margin: 0 4px;
    border-left: 1px solid var(--shadow);
    border-right: 1px solid var(--hilite);
  }
  .backend select {
    width: 200px;
  }
  .main {
    display: grid;
    grid-template-columns: 240px minmax(0, 1fr) 290px;
    gap: 4px;
    min-height: 0;
    padding: 4px;
  }
  .pane {
    display: flex;
    flex-direction: column;
    min-height: 0;
    border: 1px solid;
    border-color: var(--shadow) var(--hilite) var(--hilite) var(--shadow);
  }
  .titlebar {
    padding: 2px 6px;
    font-weight: 700;
    color: #0a1a3a;
    background: var(--panel-title);
  }
  .left :global(.tree) {
    flex: 1;
  }
  .center {
    display: grid;
    grid-template-rows: auto minmax(0, 1fr) 150px;
    gap: 4px;
    min-height: 0;
  }
  .tabs {
    display: flex;
    gap: 2px;
    padding-left: 4px;
    border-bottom: 1px solid var(--hilite);
  }
  .tab {
    position: relative;
    top: 1px;
    padding: 3px 12px;
    background: var(--face);
    border: 1px solid;
    border-color: var(--hilite) var(--dark) transparent var(--hilite);
  }
  .tab.on {
    top: 0;
    padding-bottom: 5px;
    font-weight: 700;
  }
  .work {
    min-height: 0;
    padding: 6px;
    overflow: hidden;
    border: 1px solid;
    border-color: var(--hilite) var(--dark) var(--dark) var(--hilite);
  }
  .output {
    min-height: 0;
    border: 1px solid;
    border-color: var(--shadow) var(--hilite) var(--hilite) var(--shadow);
  }
  .status {
    gap: 2px;
    padding: 2px 4px;
  }
  .cell {
    padding: 1px 6px;
    white-space: nowrap;
    border: 1px solid;
    border-color: var(--shadow) var(--hilite) var(--hilite) var(--shadow);
  }
  .grow {
    flex: 1;
    overflow: hidden;
    text-overflow: ellipsis;
  }
  .progress {
    width: 104px;
    height: 16px;
    background: var(--field);
  }
  .progress.running {
    background: repeating-linear-gradient(90deg, var(--navy) 0 8px, transparent 8px 10px);
    background-size: 20px 100%;
    animation: march 0.8s linear infinite;
  }
  @keyframes march {
    to {
      background-position: 20px 0;
    }
  }
</style>
