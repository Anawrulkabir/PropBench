<script lang="ts">
  // Settings (mockup 11), Component manager (mockup 04), Add-on manager (mockup 14) and About. Installing components
  // and add-ons (M1b, M4c), the AI assistant, GitHub and remote compute (M4b) are not built yet: their controls are
  // shown disabled. Credentials are never stored by the UI (CLAUDE.md: OS keychain only).
  import { project } from "../lib/project.svelte";
  import { applyScale, loadScale, SCALES } from "../lib/scale";
  import DialogFrame from "./DialogFrame.svelte";

  const close = () => (project.dialog = null);

  // --- settings ---
  const SECTIONS = ["Environment", "AI assistant", "GitHub", "Remote compute", "Components", "Appearance"];
  let section = $state("Environment");
  let scale = $state(loadScale());
  $effect(() => applyScale(scale));

  // --- components (README §2b) ---
  const COMPONENTS = [
    { name: "Core and calculator", contents: "Calculator, plots, projects", source: "PropBench", status: "Installed", cat: "Core" },
    { name: "CoolProp fluid library", contents: "Reference EoS and transport models", source: "CoolProp (MIT)", status: "Installed", cat: "Thermodynamic engines" },
    { name: "NIST reference transport models", contents: "Published models with check values (NISTIR 8209)", source: "NIST (public domain)", status: "Installed", cat: "Reference transport models" },
    { name: "FeOs engine", contents: "PC-SAFT, entropy-scaling transport", source: "FeOs (MIT/Apache)", status: "Available", cat: "Thermodynamic engines" },
    { name: "PC-SAFT parameter sets", contents: "Published pure-component parameters", source: "Published datasets", status: "Available", cat: "Fluid parameter sets" },
    { name: "ThermoML: viscosity", contents: "Published viscosity measurements", source: "NIST TRC archive", status: "Available", cat: "Experimental data" },
    { name: "ThermoML: density", contents: "Published density measurements", source: "NIST TRC archive", status: "Available", cat: "Experimental data" },
    { name: "ThermoML: thermal conductivity", contents: "Published measurements", source: "NIST TRC archive", status: "Available", cat: "Experimental data" },
    { name: "Mixture toolkit", contents: "Mixing rules, binary parameter fitting", source: "PropBench", status: "Planned (2.0)", cat: "Mixtures" },
    { name: "REFPROP connector", contents: "Uses your own REFPROP licence", source: "requires licence", status: "Available", cat: "Connectors" },
    { name: "Pretrained property networks", contents: "ONNX models, optional", source: "Published models", status: "Available", cat: "Machine learning" },
    { name: "Report templates", contents: "Word, PDF, Markdown", source: "PropBench", status: "Planned (M4)", cat: "Report templates" },
  ];
  const CATEGORIES = ["All components", ...new Set(COMPONENTS.map((c) => c.cat))];
  let category = $state("All components");
  let search = $state("");
  let picked = $state(COMPONENTS[0].name);
  const shownComponents = $derived(
    COMPONENTS.filter((c) => (category === "All components" || c.cat === category) && c.name.toLowerCase().includes(search.toLowerCase())),
  );
  const pickedComponent = $derived(COMPONENTS.find((c) => c.name === picked));

  // --- add-ons (README §2f) ---
  const ADDONS = [
    { name: "Data evaluation", what: "Recommended values with uncertainty from all available data", runs: "WASM", status: "verified", installed: "Available" },
    { name: "Property estimation", what: "Group contribution; PC-SAFT parameters from SMILES", runs: "Python", status: "verified", installed: "Available" },
    { name: "Binary parameter regression", what: "Fit mixture parameters to VLE and property data", runs: "Rust", status: "verified", installed: "Available" },
    { name: "VLE consistency tests", what: "Herington, Van Ness and point tests", runs: "WASM", status: "verified", installed: "Available" },
    { name: "Automatic equation search", what: "Symbolic regression (PySR)", runs: "Python", status: "community", installed: "Available" },
    { name: "Surface fitting", what: "η(T, p) and ρ(T, p) surfaces with 3D view", runs: "Rust", status: "verified", installed: "Available" },
    { name: "Advanced statistics", what: "ANOVA, robust regression, hypothesis tests", runs: "WASM", status: "verified", installed: "Available" },
    { name: "Uncertainty workbench", what: "GUM and Monte Carlo with report", runs: "WASM", status: "verified", installed: "Available" },
    { name: "Plot digitizer", what: "Data points from figures in PDFs and images", runs: "WASM", status: "community", installed: "Available" },
    { name: "Molecular simulation link", what: "LAMMPS, Green–Kubo viscosity; runs on a remote server", runs: "Python", status: "community", installed: "Available" },
  ];
  let addon = $state(ADDONS[4].name);
  let verifiedOnly = $state(false);
  const shownAddons = $derived(ADDONS.filter((a) => !verifiedOnly || a.status === "verified"));
</script>

{#if project.dialog === "settings"}
  <DialogFrame title="Settings – {section}" width="1000px" height="540px" onclose={close}>
    <div class="split">
      <div class="well list">
        {#each SECTIONS as s (s)}
          <button class="item" class:sel={section === s} onclick={() => (section = s)}>{s}</button>
        {/each}
      </div>
      <div class="pane">
        {#if section === "Environment"}
          <fieldset class="group">
            <legend>Project environment</legend>
            <div class="form">
              <span>Location</span><span class="mono">app data / envs / {project.name.toLowerCase().replace(/\s+/g, "-")}</span>
              <span>Python</span><span class="mono">3.12 (bundled, managed by uv)</span>
              <span>Storage limit</span><select class="field" disabled><option>5 GB</option></select>
              <span>Script limits</span><span class="mono">time 10 min, memory 4 GB</span>
            </div>
            <label class="row"><input type="checkbox" checked disabled /> Never modify system Python or PATH (always on)</label>
            <p class="muted">Per-project environments and limits: M1c.</p>
          </fieldset>
        {:else if section === "AI assistant"}
          <fieldset class="group">
            <legend>AI assistant</legend>
            <div class="form">
              <span>Provider</span><select class="field" disabled><option>Ollama · local model</option></select>
              <span>Endpoint</span><input class="field" disabled placeholder="https://[provider endpoint]" />
              <span>API key</span><input class="field" disabled type="password" placeholder="stored in the OS keychain" />
              <span>Send to provider</span><select class="field" disabled><option>Summaries only</option></select>
            </div>
            <p class="muted">Keys go to the system keychain, never into project files. AI output never changes data without your confirmation. Planned: M4b.</p>
          </fieldset>
        {:else if section === "GitHub"}
          <fieldset class="group">
            <legend>GitHub</legend>
            <div class="form"><span>Account</span><span>not connected</span><span>Repository</span><input class="field" disabled placeholder="[owner/repository]" /></div>
            <label class="row"><input type="checkbox" disabled /> Commit on every named snapshot</label>
            <div class="row"><span class="spacer"></span><button class="btn" disabled>Sign in with GitHub</button></div>
            <p class="muted">Planned: M4b.</p>
          </fieldset>
        {:else if section === "Remote compute"}
          <fieldset class="group">
            <legend>Remote compute</legend>
            <div class="form"><span>Host</span><input class="field" disabled placeholder="[user@gpu-server]" /><span>SSH key</span><select class="field" disabled><option>Use SSH agent</option></select></div>
            <p class="muted">Only over SSH with your keys; no listening ports. Planned: M4b.</p>
          </fieldset>
        {:else if section === "Components"}
          <p>Components are managed in Tools › Components.</p>
          <button class="btn" onclick={() => (project.dialog = "components")}>Open the component manager</button>
        {:else}
          <fieldset class="group">
            <legend>Appearance</legend>
            <div class="form">
              <label for="st-scale">Text size</label>
              <select id="st-scale" class="field" bind:value={scale}>{#each SCALES as v (v)}<option value={v}>{v} %</option>{/each}</select>
              <span>Theme</span><span>Classic (as the design mockups)</span>
            </div>
          </fieldset>
        {/if}
      </div>
    </div>
    {#snippet footer()}
      <span class="spacer"></span>
      <button class="btn default" onclick={close}>OK</button>
      <button class="btn" onclick={close}>Cancel</button>
    {/snippet}
  </DialogFrame>
{:else if project.dialog === "components"}
  <DialogFrame title="Component Manager" width="1000px" height="620px" onclose={close}>
    <div class="split">
      <div class="well list">
        {#each CATEGORIES as c (c)}<button class="item" class:sel={category === c} onclick={() => (category = c)}>🗀 {c}</button>{/each}
      </div>
      <div class="pane">
        <div class="row"><span>Search:</span><input class="field grow" bind:value={search} /></div>
        <div class="well">
          <table class="grid">
            <thead><tr><th></th><th>Component</th><th>Contents</th><th>Source</th><th>Status</th></tr></thead>
            <tbody>
              {#each shownComponents as c (c.name)}
                <tr class="clickable" class:sel={picked === c.name} onclick={() => (picked = c.name)}>
                  <td><input type="checkbox" checked={c.status === "Installed"} disabled /></td>
                  <td>{c.name}</td><td>{c.contents}</td><td>{c.source}</td>
                  <td class:ok={c.status === "Installed"} class:link={c.status === "Available"}>{c.status}</td>
                </tr>
              {/each}
            </tbody>
          </table>
        </div>
        {#if pickedComponent}
          <fieldset class="group">
            <legend>Details: {pickedComponent.name}</legend>
            <table class="props"><tbody>
              <tr><td>Contents</td><td>{pickedComponent.contents}</td></tr>
              <tr><td>Source</td><td>{pickedComponent.source}</td></tr>
              <tr><td>Checksum</td><td>verified after download (M1b)</td></tr>
            </tbody></table>
          </fieldset>
        {/if}
      </div>
    </div>
    {#snippet footer()}
      <span class="muted">Source: PropBench registry. Download, checksum verification and offline install: M1b.</span>
      <span class="spacer"></span>
      <button class="btn" disabled>Install from file…</button>
      <button class="btn" disabled>Remove</button>
      <button class="btn" disabled>Install selected</button>
      <button class="btn default" onclick={close}>Close</button>
    {/snippet}
  </DialogFrame>
{:else if project.dialog === "addons"}
  <DialogFrame title="Add-on Manager" width="1100px" height="620px" onclose={close}>
    <div class="row"><button class="btn">Available ({ADDONS.length})</button><span class="spacer"></span><label class="row"><input type="checkbox" bind:checked={verifiedOnly} /> Verified only</label></div>
    <div class="well">
      <table class="grid">
        <thead><tr><th>Add-on</th><th>What it does</th><th>Runs as</th><th>Status</th><th>Installed</th></tr></thead>
        <tbody>
          {#each shownAddons as a (a.name)}
            <tr class="clickable" class:sel={addon === a.name} onclick={() => (addon = a.name)}>
              <td><b>{a.name}</b></td><td>{a.what}</td><td>{a.runs}</td>
              <td class:ok={a.status === "verified"} class:muted={a.status !== "verified"}>{a.status === "verified" ? "⛉ verified" : "community"}</td>
              <td class="link">{a.installed}</td>
            </tr>
          {/each}
        </tbody>
      </table>
    </div>
    <div class="split2">
      <fieldset class="group">
        <legend>Details: {addon}</legend>
        <table class="props"><tbody>
          <tr><td>Runs as</td><td>{ADDONS.find((a) => a.name === addon)?.runs === "Python" ? "Python, in the project environment" : "sandboxed (WASM)"}</td></tr>
          <tr><td>Check-value tests</td><td>[status from registry]</td></tr>
          <tr><td>Signed by</td><td>[publisher key]</td></tr>
        </tbody></table>
      </fieldset>
      <fieldset class="group">
        <legend>Permissions requested (approve to install)</legend>
        <table class="grid"><tbody>
          <tr><td>✓ Read and write this project's data</td><td class="ok">requested</td></tr>
          <tr><td>✓ Compute: up to 4 threads, 4 GB memory</td><td class="ok">requested</td></tr>
          <tr><td>✗ Files outside the project folder</td><td class="error">not requested: denied</td></tr>
          <tr><td>✗ Network: any other host</td><td class="error">not requested: denied</td></tr>
        </tbody></table>
      </fieldset>
    </div>
    {#snippet footer()}
      <span class="muted">Signature checked before install. Add-ons from published methods and open data only. Plug-in system: M4c.</span>
      <span class="spacer"></span>
      <button class="btn" disabled>Developer kit…</button>
      <button class="btn" disabled>Approve and install</button>
      <button class="btn default" onclick={close}>Close</button>
    {/snippet}
  </DialogFrame>
{:else if project.dialog === "about"}
  <DialogFrame title="About PropBench" width="520px" height="320px" onclose={close}>
    <p><b>PropBench 0.1.0</b> — an open desktop workbench for thermophysical property models of new fluids.</p>
    <p>MIT licence. Science in a Python worker calling CoolProp, FeOs, NumPy and SciPy; Tauri shell.</p>
    <p class="muted">Reference models are implemented from the original publications (e.g. NISTIR 8209, Huber 2018) and verified against their check values.</p>
    {#snippet footer()}<span class="spacer"></span><button class="btn default" onclick={close}>OK</button>{/snippet}
  </DialogFrame>
{/if}

<style>
  .split {
    display: grid;
    grid-template-columns: 210px 1fr;
    gap: 10px;
    height: 100%;
  }
  .split2 {
    display: grid;
    grid-template-columns: 1fr 1fr;
    gap: 10px;
    margin-top: 8px;
  }
  .list {
    display: flex;
    flex-direction: column;
    padding: 4px;
  }
  .item {
    padding: 3px 6px;
    text-align: left;
    background: none;
    border: 0;
  }
  .item.sel {
    color: #fff;
    background: var(--navy);
  }
  .pane {
    display: grid;
    gap: 8px;
    align-content: start;
  }
  .form {
    display: grid;
    grid-template-columns: 130px 1fr;
    gap: 5px 8px;
    align-items: center;
    margin-bottom: 6px;
  }
  .grow {
    flex: 1;
  }
  .link {
    color: var(--navy);
  }
</style>
