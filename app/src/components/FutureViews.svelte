<script lang="ts">
  // Code and terminal (mockup 10), Setup builder (17) and CAD & simulation (18): laid out as designed; the runtimes
  // behind them come in later milestones (M1c environments, M4b AI and remote, 0.3 setup builder and simulation).
  import { project } from "../lib/project.svelte";

  interface Props {
    view: "code" | "setup" | "cad";
  }
  let { view }: Props = $props();

  let script = $state(`import propbench as pb

proj = pb.open("${project.name}.pbp")
data = proj.datasets
# ECS with R134a as reference, linear shape function, fitted dilute-gas factor
model = pb.models.ECS(reference="R134a", shape="linear", dilute_gas_factor=True)

study = pb.validate(model, data, scheme="loso", bootstrap=200, seed=2026)
print(study.summary())
`);

  const GALLERY: Record<string, string[]> = {
    Flow: ["Pump", "Syringe pump", "Valve", "Capillary", "Pipe"],
    Thermal: ["Heater", "Cooler", "Plate HX", "Thermostat bath"],
    Vessels: ["Vessel", "Sight glass", "Gas cylinder", "Vacuum"],
    Sensors: ["Flowmeter", "Thermometer", "Pressure gauge", "ΔP transducer", "Data logger"],
  };
</script>

{#if view === "code"}
  <div class="code">
    <div class="files well">
      <div class="head">Files</div>
      <div>🗀 {project.name}</div>
      <div class="ind">🗀 scripts</div>
      <div class="ind2 sel">fit_ecs.py</div>
      <div class="ind">🗀 data</div>
      {#each project.datasets as d (d.name)}<div class="ind2">{d.name}.parquet</div>{/each}
      <div class="ind">🗀 environment</div>
      <div class="ind2">pyproject.toml</div>
      <div class="ind2">uv.lock</div>
    </div>
    <div class="editor-col">
      <div class="row">
        <button class="btn" disabled title="Scripts run in the project environment: M1c">▷ Run in project environment</button>
        <button class="btn" disabled title="Remote engine over SSH: M4b">Run on: local ▾</button>
        <span class="spacer"></span>
        <span class="muted">Python 3.12 · env: {project.name.toLowerCase().replace(/\s+/g, "-")}</span>
      </div>
      <textarea class="field editor mono" bind:value={script} spellcheck="false" aria-label="Script editor"></textarea>
      <div class="terminal mono">
        <div>PropBench terminal · project environment (isolated)</div>
        <div class="dim">The terminal and script runner open in the project environment in M1c; nothing runs outside it.</div>
      </div>
    </div>
    <aside class="ai">
      <div class="head">AI assistant</div>
      <div class="notice">Planned for M4b. AI output never changes code or data without your confirmation, and keys stay in the OS keychain.</div>
      <textarea class="field" disabled placeholder="Ask about this project…"></textarea>
      <div class="row"><span class="spacer"></span><button class="btn" disabled>Send</button></div>
    </aside>
  </div>
{:else if view === "setup"}
  <div class="builder">
    <aside class="gallery well">
      <input class="field" placeholder="Search components" disabled />
      {#each Object.entries(GALLERY) as [group, items] (group)}
        <div class="group-title">{group}</div>
        <div class="tiles">{#each items as it (it)}<button class="btn tile" disabled>{it}</button>{/each}</div>
      {/each}
    </aside>
    <div class="canvas-col">
      <div class="row">
        {#each ["Select", "Connect pipe", "Text", "Group", "Align"] as t (t)}<button class="btn" disabled>{t}</button>{/each}
        <span class="spacer"></span><button class="btn" disabled>Check connections</button><button class="btn" disabled>Simulate loop (1D)</button>
      </div>
      <div class="grid-canvas"><div class="notice">Setup builder (node canvas, 1D loop simulation with the fluids library, uncertainty inputs to the GUM budget): planned for 0.3.</div></div>
    </div>
  </div>
{:else}
  <div class="builder">
    <aside class="gallery well">
      <div class="group-title">Simulation tree</div>
      <div>🗀 Study: (new)</div>
      <div class="ind">Geometry: STEP import (OpenCascade)</div>
      <div class="ind">Mesh: Gmsh</div>
      <div class="ind">Physics: fluid properties from PropBench</div>
      <div class="ind">Solver: OpenFOAM (external process)</div>
    </aside>
    <div class="canvas-col">
      <div class="row">{#each ["Geometry", "Mesh", "Physics", "Solve", "Results"] as t (t)}<button class="btn" disabled>{t}</button>{/each}</div>
      <div class="grid-canvas"><div class="notice">CAD & simulation (geometry, meshing and CFD/FEA as separate GPL processes, property uncertainty propagated through ±U runs): planned for 0.3+.</div></div>
    </div>
  </div>
{/if}

<style>
  .code {
    display: grid;
    grid-template-columns: 170px minmax(0, 1fr) 240px;
    gap: 6px;
    height: 100%;
    min-height: 0;
  }
  .files,
  .gallery {
    padding: 4px;
    overflow: auto;
  }
  .head,
  .group-title {
    margin: 4px 0;
    font-weight: 700;
  }
  .ind {
    padding-left: 12px;
  }
  .ind2 {
    padding-left: 24px;
  }
  .sel {
    color: #fff;
    background: var(--navy);
  }
  .editor-col,
  .canvas-col {
    display: flex;
    flex-direction: column;
    gap: 4px;
    min-height: 0;
  }
  .editor {
    flex: 1;
    min-height: 0;
    padding: 6px;
    font-size: 12px;
    line-height: 1.5;
    resize: none;
  }
  .terminal {
    height: 110px;
    padding: 6px;
    color: #cfe;
    background: #111;
  }
  .dim {
    color: #8a8;
  }
  .ai {
    display: grid;
    gap: 6px;
    align-content: start;
  }
  .ai textarea {
    height: 80px;
  }
  .builder {
    display: grid;
    grid-template-columns: 220px minmax(0, 1fr);
    gap: 6px;
    height: 100%;
    min-height: 0;
  }
  .tiles {
    display: grid;
    grid-template-columns: repeat(3, 1fr);
    gap: 3px;
  }
  .tile {
    min-height: 40px;
    padding: 2px;
    font-size: 10px;
  }
  .grid-canvas {
    flex: 1;
    min-height: 0;
    padding: 20px;
    background-color: #fbfaf6;
    background-image: linear-gradient(#e6e3da 1px, transparent 1px), linear-gradient(90deg, #e6e3da 1px, transparent 1px);
    background-size: 20px 20px;
    border: 1px solid var(--shadow);
  }
</style>
