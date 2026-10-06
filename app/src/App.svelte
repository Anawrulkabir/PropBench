<script lang="ts">
  // Main window (design/mockups/01_Main): menu bar, toolbar, project tree, document tabs, properties, output, status
  // bar. The UI never computes: every action goes through the worker (lib/project.svelte.ts → Tauri → pb-engine).
  import CalculatorView from "./components/CalculatorView.svelte";
  import ConsistencyView from "./components/ConsistencyView.svelte";
  import DataView from "./components/DataView.svelte";
  import DeviationView from "./components/DeviationView.svelte";
  import FittingView from "./components/FittingView.svelte";
  import FitView from "./components/FitView.svelte";
  import GraphStudioView from "./components/GraphStudioView.svelte";
  import Icon from "./components/Icon.svelte";
  import ImportDialog from "./components/ImportDialog.svelte";
  import MenuBar from "./components/MenuBar.svelte";
  import OutputPanel from "./components/OutputPanel.svelte";
  import PlannedView from "./components/PlannedView.svelte";
  import ProjectTree from "./components/ProjectTree.svelte";
  import PropertiesPanel from "./components/PropertiesPanel.svelte";
  import ResultsView from "./components/ResultsView.svelte";
  import StudyView from "./components/StudyView.svelte";
  import WorksheetView from "./components/WorksheetView.svelte";
  import WizardDialog from "./components/WizardDialog.svelte";
  import SettingsDialogs from "./components/SettingsDialogs.svelte";
  import SurfaceView from "./components/SurfaceView.svelte";
  import ExperimentView from "./components/ExperimentView.svelte";
  import FutureViews from "./components/FutureViews.svelte";
  import CodeView from "./components/CodeView.svelte";
  import CurveFitView from "./components/CurveFitView.svelte";
  import UncertaintyView from "./components/UncertaintyView.svelte";
  import ReferencesDialog from "./components/ReferencesDialog.svelte";
  import { applyScale, loadScale } from "./lib/scale";
  import type { MenuItem } from "./lib/menu";
  import { project, type View } from "./lib/project.svelte";

  const LABELS: Record<View, string> = {
    data: "Data check",
    consistency: "Data consistency",
    deviations: "Deviations",
    fit: "Models",
    fitting: "Fitting",
    study: "Study setup",
    results: "Results",
    worksheet: "Worksheet",
    graph: "Graph studio",
    calculator: "Property calculator",
    code: "Code",
    surface: "3D surface",
    experiment: "Experiment planner",
    setup: "Setup builder",
    cad: "CAD & simulation",
    curvefit: "Curve fit",
    uncertainty: "Uncertainty budget",
  };
  const FIXED = new Set<View>(["data", "consistency", "deviations", "fit", "fitting", "study", "results"]);

  const hasData = $derived(project.datasets.length > 0);
  const hasModels = $derived(project.candidates.length > 0);
  const busy = $derived(!!project.busy);

  function tabLabel(v: View): string {
    if (v === "worksheet" && project.worksheet) return `Worksheet: ${project.worksheet}`;
    if (v === "fitting") {
      const c = project.selected?.type === "candidate" ? project.candidate(project.selected.id) : project.candidates[0];
      return c ? `Fit: ${c.label}` : "Fitting";
    }
    return LABELS[v];
  }

  function fitSelected() {
    const id = project.selected?.type === "candidate" ? project.selected.id : project.candidates[0]?.id;
    if (id) {
      project.view = "fitting";
      project.fit(id);
    }
  }

  function validate() {
    project.view = "study";
    project.runStudy();
  }

  function exportResults() {
    const data = {
      generator: "PropBench",
      exported: new Date().toISOString(),
      datasets: project.datasets.map((d) => d.name),
      masks: project.masks,
      rule: project.locked,
      selection: project.selection,
      candidates: project.candidates.map((c) => ({ label: c.label, model: c.fit?.model ?? c.start, fit: c.fit?.summary, study: c.study })),
      consistency: project.consistency,
      comparison: project.comparison,
    };
    const url = URL.createObjectURL(new Blob([JSON.stringify(data, null, 1)], { type: "application/json" }));
    const a = document.createElement("a");
    a.href = url;
    a.download = "propbench-results.json";
    a.click();
    URL.revokeObjectURL(url);
    project.note("Results exported as propbench-results.json");
  }

  function snapshotPrompt() {
    const label = window.prompt("Snapshot name", `Snapshot ${project.snapshots.length + 1}`);
    if (label) project.snapshot(label);
  }

  function onKey(e: KeyboardEvent) {
    if (!(e.ctrlKey || e.metaKey)) return;
    const k = e.key.toLowerCase();
    if (k === "s") {
      e.preventDefault();
      project.saveProject(e.shiftKey);
    } else if (k === "z" && !(e.target instanceof HTMLInputElement || e.target instanceof HTMLTextAreaElement)) {
      e.preventDefault();
      project.undo();
    } else if (k === "o") {
      e.preventDefault();
      project.openProject();
    }
  }

  // Recovery copy of unsaved work every minute (app data folder only); offer the last one at start-up.
  $effect(() => {
    project.recover();
    const timer = setInterval(() => project.autosave(), 60_000);
    return () => clearInterval(timer);
  });
  const menus: { label: string; items: MenuItem[] }[] = $derived([
    {
      label: "File",
      items: [
        { label: "New project", action: () => project.newProject(), disabled: busy },
        { label: "New project wizard…", action: () => (project.dialog = "wizard") },
        { label: "Open project…", action: () => project.openProject(), disabled: busy, note: "Ctrl+O" },
        { label: "Save project", action: () => project.saveProject(), disabled: busy, note: "Ctrl+S" },
        { label: "Save project as…", action: () => project.saveProject(true), disabled: busy, note: "Ctrl+Shift+S" },
        { separator: true, label: "" },
        { label: "Create snapshot…", action: snapshotPrompt, disabled: busy },
        ...project.snapshots
          .slice(-8)
          .reverse()
          .map((s) => ({ label: `Restore snapshot ${s.id}: ${s.label}`, action: () => project.restore(s.id), disabled: busy })),
        { separator: true, label: "" },
        { label: "Import data…", action: () => (project.importOpen = true), disabled: busy },
        { label: "Export results (JSON)…", action: exportResults, disabled: !hasData },
        { separator: true, label: "" },
        { label: "Settings…", action: () => (project.dialog = "settings") },
      ],
    },
    {
      label: "Edit",
      items: [
        {
          label: project.undoStack.length ? `Undo ${project.undoStack[project.undoStack.length - 1].label}` : "Undo",
          action: () => project.undo(),
          disabled: busy || !project.undoStack.length,
          note: "Ctrl+Z",
        },
        { label: "Mask points in worksheet…", action: () => project.datasets[0] && project.openWorksheet(project.worksheet ?? project.datasets[0].name), disabled: !hasData },
      ],
    },
    {
      label: "View",
      items: (["data", "consistency", "deviations", "fit", "fitting", "study", "results", "graph", "calculator"] as View[]).map((v) => ({
        label: LABELS[v],
        action: () => project.open(v),
      })),
    },
    {
      label: "Data",
      items: [
        { label: "Import…", action: () => (project.importOpen = true), disabled: busy },
        { label: "Published data from components…", action: () => (project.dialog = "components") },
        { label: "Check data", action: () => project.checkData(), disabled: busy || !hasData },
        { label: "Consistency…", action: () => { project.open("consistency"); project.analyzeConsistency(); }, disabled: busy || !hasData },
        { label: "Open worksheet", action: () => project.datasets[0] && project.openWorksheet(project.worksheet ?? project.datasets[0].name), disabled: !hasData },
      ],
    },
    {
      label: "Models",
      items: [
        { label: "Add / edit candidate models", action: () => project.open("fit") },
        { label: "Fit selected model", action: fitSelected, disabled: busy || !hasModels },
        { label: "Fit all models", action: () => project.fitAll(), disabled: busy || !hasModels },
        { label: "Compare with reference models", action: () => { project.open("results"); project.compareModels(); }, disabled: busy || !hasData },
      ],
    },
    {
      label: "Validate",
      items: [
        { label: "Study setup", action: () => project.open("study") },
        { label: "Lock selection rule", action: () => project.lockRule(), disabled: busy || !!project.locked },
        { label: "Run study (fit, validate, select)", action: validate, disabled: busy || !hasModels },
        { label: "Deviation plots", action: () => project.open("deviations") },
        { label: "Results", action: () => project.open("results") },
      ],
    },
    { label: "Report", items: [{ label: "Generate report…", disabled: true, note: "M4" }, { label: "Export to CoolProp…", disabled: true, note: "M4" }] },
    {
      label: "Tools",
      items: [
        { label: "Property calculator", action: () => project.open("calculator") },
        { label: "Graph studio", action: () => project.open("graph") },
        { label: "General curve fit", action: () => project.open("curvefit") },
        { label: "Uncertainty budget (GUM)", action: () => project.open("uncertainty") },
        { label: "References…", action: () => (project.dialog = "references") },
        { label: "Code and terminal", action: () => project.open("code") },
        { separator: true, label: "" },
        { label: "3D surface", action: () => project.open("surface") },
        { label: "Experiment planner", action: () => project.open("experiment") },
        { label: "Setup builder", action: () => project.open("setup") },
        { label: "CAD & simulation", action: () => project.open("cad") },
        { separator: true, label: "" },
        { label: "Components…", action: () => (project.dialog = "components") },
        { label: "Add-ons…", action: () => (project.dialog = "addons") },
      ],
    },
    { label: "Window", items: [{ label: "Reset layout", action: resetLayout }, { label: "Close extra tabs", action: () => (project.tabs = project.tabs.filter((t) => FIXED.has(t))) }] },
    { label: "Help", items: [{ label: "CF3I tutorial", action: () => project.loadExample().then(() => project.open("data")) }, { label: "About PropBench", action: () => (project.dialog = "about") }] },
  ]);

  applyScale(loadScale());

  // --- resizable panes (per-viewer layout, kept in browser storage) ---
  const DEFAULT_LAYOUT = { left: 240, right: 290, output: 150 };
  function loadLayout(): typeof DEFAULT_LAYOUT {
    try {
      const raw = localStorage.getItem("propbench.layout");
      return raw ? { ...DEFAULT_LAYOUT, ...JSON.parse(raw) } : { ...DEFAULT_LAYOUT };
    } catch {
      return { ...DEFAULT_LAYOUT };
    }
  }
  let layout = $state(loadLayout());
  $effect(() => {
    try {
      localStorage.setItem("propbench.layout", JSON.stringify(layout));
    } catch {
      /* storage unavailable: layout is not remembered */
    }
  });
  function resetLayout() {
    layout = { ...DEFAULT_LAYOUT };
  }
  function drag(which: "left" | "right" | "output", event: PointerEvent) {
    event.preventDefault();
    const start = { x: event.clientX, y: event.clientY, ...layout };
    const move = (e: PointerEvent) => {
      if (which === "left") layout.left = Math.min(500, Math.max(150, start.left + e.clientX - start.x));
      if (which === "right") layout.right = Math.min(520, Math.max(180, start.right - (e.clientX - start.x)));
      if (which === "output") layout.output = Math.min(420, Math.max(60, start.output - (e.clientY - start.y)));
    };
    const up = () => {
      window.removeEventListener("pointermove", move);
      window.removeEventListener("pointerup", up);
    };
    window.addEventListener("pointermove", move);
    window.addEventListener("pointerup", up);
  }

  const loso = $derived.by(() => {
    const c = project.candidates.find((x) => x.label === project.selection?.chosen) ?? project.candidates.find((x) => x.study);
    const cv = c?.study?.cross_validation[project.rule.validation];
    return cv ? `${project.rule.validation.toUpperCase()} ${cv.folds.filter((f) => f.success).length}/${cv.folds.length}` : "";
  });
</script>

<svelte:head><title>{project.name}{project.isDirty() ? " *" : ""} - PropBench</title></svelte:head>
<svelte:window onkeydown={onKey} />

<div class="window">
  <MenuBar {menus} />
  <div class="toolbar row">
    <button class="tool btn" onclick={() => project.openProject()} disabled={busy} title="Open a project (Ctrl+O)"><Icon name="open" />Open</button>
    <button class="tool btn" onclick={() => project.saveProject()} disabled={busy} title="Save the project (Ctrl+S)"><Icon name="save" />Save</button>
    <span class="sep"></span>
    <button class="tool btn" onclick={() => (project.importOpen = true)} disabled={busy}><Icon name="import" />Import</button>
    <button class="tool btn" onclick={() => project.checkData()} disabled={busy || !hasData}><Icon name="check" />Check</button>
    <button class="tool btn" onclick={() => { project.open("consistency"); project.analyzeConsistency(); }} disabled={busy || !hasData}>
      <Icon name="consistency" />Consistency
    </button>
    <span class="sep"></span>
    <button class="tool btn" onclick={fitSelected} disabled={busy || !hasModels}><Icon name="fit" />Fit</button>
    <button class="tool btn primary" onclick={validate} disabled={busy || !hasModels}><Icon name="validate" />Validate</button>
    <button class="tool btn stop" onclick={() => project.stop()} disabled={!busy}><Icon name="stop" />Stop</button>
    <span class="sep"></span>
    <button class="tool btn" disabled title="Report generator: M4"><Icon name="report" />Report</button>
    <button class="tool btn" onclick={exportResults} disabled={!hasData}><Icon name="export" />Export</button>
    <span class="spacer"></span>
    <label class="row backend">
      Backend:
      <select class="field" aria-label="Backend"><option>CoolProp – reference EoS</option></select>
    </label>
  </div>

  <div class="main" style="grid-template-columns: {layout.left}px 4px minmax(0, 1fr) 4px {layout.right}px">
    <section class="pane left">
      <header class="titlebar">Project</header>
      <ProjectTree />
    </section>
    <div class="splitter v" role="separator" aria-orientation="vertical" onpointerdown={(e) => drag("left", e)}></div>

    <section class="center" style="grid-template-rows: auto minmax(0, 1fr) 4px {layout.output}px">
      <div class="tabs" role="tablist">
        {#each project.tabs as t (t)}
          <div class="tab" class:on={project.view === t}>
            <button role="tab" aria-selected={project.view === t} onclick={() => (project.view = t)}>{tabLabel(t)}</button>
            {#if !FIXED.has(t)}<button class="close" aria-label="Close {tabLabel(t)}" onclick={() => project.closeTab(t)}>×</button>{/if}
          </div>
        {/each}
      </div>
      <div class="work">
        {#if project.view === "data"}<DataView />
        {:else if project.view === "consistency"}<ConsistencyView />
        {:else if project.view === "deviations"}<DeviationView />
        {:else if project.view === "fit"}<FitView />
        {:else if project.view === "fitting"}<FittingView />
        {:else if project.view === "study"}<StudyView />
        {:else if project.view === "results"}<ResultsView />
        {:else if project.view === "worksheet"}<WorksheetView />
        {:else if project.view === "calculator"}<CalculatorView />
        {:else if project.view === "graph"}<GraphStudioView />
        {:else if project.view === "surface"}<SurfaceView />
        {:else if project.view === "experiment"}<ExperimentView />
        {:else if project.view === "code"}<CodeView />
        {:else if project.view === "curvefit"}<CurveFitView />
        {:else if project.view === "uncertainty"}<UncertaintyView />
        {:else if project.view === "setup" || project.view === "cad"}<FutureViews view={project.view} />
        {:else}
          <PlannedView title={LABELS[project.view]} milestone="see the roadmap" description="This screen is being built." />
        {/if}
      </div>
      <div class="splitter h" role="separator" aria-orientation="horizontal" onpointerdown={(e) => drag("output", e)}></div>
      <div class="output"><OutputPanel /></div>
    </section>

    <div class="splitter v" role="separator" aria-orientation="vertical" onpointerdown={(e) => drag("right", e)}></div>
    <section class="pane right"><PropertiesPanel /></section>
  </div>

  <footer class="status row">
    <span class="cell grow">{project.busy ? `${project.busy}…` : project.status}</span>
    <span class="cell">Selection rule: {project.locked ? "locked" : "open"}</span>
    <span class="cell">Seed {project.settings.seed}</span>
    {#if loso}<span class="cell">{loso}</span>{/if}
    <span class="cell">{project.datasets.length} datasets · {project.candidates.length} models</span>
    <span class="cell">PropBench 0.1.0</span>
    <span class="cell progress" class:running={busy} aria-hidden="true"></span>
  </footer>
</div>

{#if project.importOpen}<ImportDialog />{/if}
{#if project.dialog === "wizard"}<WizardDialog />
{:else if project.dialog === "references"}<ReferencesDialog />
{:else if project.dialog && project.dialog !== "import"}<SettingsDialogs />{/if}

<style>
  .window {
    display: grid;
    grid-template-rows: auto auto 1fr auto;
    height: 100%;
  }
  .toolbar {
    gap: 2px;
    padding: 3px 6px;
    border-top: 1px solid var(--hilite);
    border-bottom: 1px solid var(--shadow);
    box-shadow: 0 1px 0 var(--hilite);
  }
  .tool {
    display: flex;
    flex-direction: column;
    gap: 2px;
    align-items: center;
    min-width: 52px;
    padding: 3px 6px 2px;
  }
  .tool.primary:not(:disabled) {
    background: #c9d8c6;
  }
  .tool.stop:not(:disabled) :global(.icon) {
    color: var(--error);
  }
  .sep {
    width: 2px;
    height: 38px;
    margin: 0 4px;
    border-left: 1px solid var(--shadow);
    border-right: 1px solid var(--hilite);
  }
  .backend select {
    width: 200px;
  }
  .main {
    display: grid;
    min-height: 0;
    padding: 4px;
  }
  .splitter.v {
    cursor: col-resize;
  }
  .splitter.h {
    cursor: row-resize;
  }
  .splitter:hover {
    background: var(--shadow);
  }
  .pane {
    display: flex;
    flex-direction: column;
    min-height: 0;
    min-width: 0;
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
    min-height: 0;
    min-width: 0;
  }
  .tabs {
    display: flex;
    flex-wrap: wrap;
    gap: 2px;
    padding-left: 4px;
  }
  .tab {
    position: relative;
    top: 1px;
    display: flex;
    align-items: center;
    background: var(--face);
    border: 1px solid;
    border-color: var(--hilite) var(--dark) transparent var(--hilite);
  }
  .tab button {
    padding: 3px 10px;
    background: none;
    border: 0;
  }
  .tab .close {
    padding: 0 5px 0 0;
    color: var(--muted);
  }
  .tab.on {
    top: 0;
    padding-bottom: 2px;
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
