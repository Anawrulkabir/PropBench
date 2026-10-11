<script lang="ts">
  // Setup builder (17) and CAD & simulation (18): laid out as designed; the setup builder and simulation runtime
  // come in 0.3.

  interface Props {
    view: "setup" | "cad";
  }
  let { view }: Props = $props();



  const GALLERY: Record<string, string[]> = {
    Flow: ["Pump", "Syringe pump", "Valve", "Capillary", "Pipe"],
    Thermal: ["Heater", "Cooler", "Plate HX", "Thermostat bath"],
    Vessels: ["Vessel", "Sight glass", "Gas cylinder", "Vacuum"],
    Sensors: ["Flowmeter", "Thermometer", "Pressure gauge", "ΔP transducer", "Data logger"],
  };
</script>

{#if view === "setup"}
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
  .gallery {
    padding: 4px;
    overflow: auto;
  }
  .group-title {
    margin: 4px 0;
    font-weight: 700;
  }
  .ind {
    padding-left: 12px;
  }
  .canvas-col {
    display: flex;
    flex-direction: column;
    gap: 4px;
    min-height: 0;
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
