<script lang="ts">
  // Plug-in manager (mockup 14, README §2f): installed plug-ins, their signature and permissions; install from a
  // folder, approve the declared permissions (nothing runs before), check-value harness ("verified"), evaluate a
  // model plug-in, revoke and remove. Verification and enforcement happen in the shell (pb-plugin).
  import { invoke } from "@tauri-apps/api/core";
  import { ask, open as openDialog } from "@tauri-apps/plugin-dialog";
  import { errorMessage, inTauri } from "../lib/api";
  import { approvalText, type CheckResult, type Installed, type PluginPackage, runsAs, signerLabel, verifiedLabel } from "../lib/plugins";
  import { project } from "../lib/project.svelte";
  import DialogFrame from "./DialogFrame.svelte";

  const PLANNED = [
    { name: "Data evaluation", what: "Recommended values with uncertainty from all available data", runs: "WASM" },
    { name: "Property estimation", what: "Group contribution; PC-SAFT parameters from SMILES", runs: "Python" },
    { name: "VLE consistency tests", what: "Herington, Van Ness and point tests", runs: "WASM" },
    { name: "Automatic equation search", what: "Symbolic regression (PySR)", runs: "Python" },
    { name: "Plot digitizer", what: "Data points from figures in PDFs and images", runs: "WASM" },
    { name: "Molecular simulation link", what: "LAMMPS, Green–Kubo viscosity; runs on a remote server", runs: "Python" },
  ];

  let tab = $state<"installed" | "planned" | "sdk">("installed");
  let plugins = $state<Installed[]>([]);
  let selected = $state<string | null>(null);
  let checks = $state<Record<string, CheckResult[]>>({});
  let status = $state("");
  let busy = $state(false);
  let evalT = $state(300);
  let evalRho = $state(0);
  let evalOut = $state("");
  const envName = $derived(project.name || "project");
  const current = $derived(plugins.find((p) => p.manifest.id === selected) ?? null);

  async function refresh() {
    if (!inTauri()) {
      status = "Plug-ins run in the desktop app.";
      return;
    }
    try {
      plugins = (await invoke<Installed[] | null>("plugin_list")) ?? [];
      if (!current && plugins.length) selected = plugins[0].manifest.id;
    } catch (err) {
      status = errorMessage(err);
    }
  }
  $effect(() => {
    refresh();
  });

  async function act<T>(label: string, step: () => Promise<T>): Promise<T | null> {
    busy = true;
    status = `${label}…`;
    try {
      const out = await step();
      status = `${label}: done`;
      return out;
    } catch (err) {
      status = `${label} failed: ${errorMessage(err)}`;
      return null;
    } finally {
      busy = false;
      await refresh();
    }
  }

  async function approve(pkg: PluginPackage) {
    const ok = await ask(approvalText(pkg), { title: "Approve plug-in permissions?", kind: "warning" });
    if (ok !== true) {
      status = `${pkg.id} installed, not approved: it will not run`;
      return;
    }
    await act(`Approve ${pkg.id}`, () => invoke("plugin_approve", { id: pkg.id, digest: pkg.digest, allowUnsigned: pkg.signer.status === "unsigned" }));
    project.audit("plugin", `approved ${pkg.id} ${pkg.version} (${pkg.digest.slice(0, 16)})`);
  }

  async function installFolder() {
    const dir = await openDialog({ directory: true, title: "Plug-in folder (with plugin.toml)" });
    if (typeof dir !== "string") return;
    const pkg = await act("Install", () => invoke<PluginPackage>("plugin_install", { dir }));
    if (pkg) {
      selected = pkg.id;
      await approve(pkg);
    }
  }

  async function approveCurrent() {
    if (!current) return;
    const m = current.manifest;
    await approve({ id: m.id, name: m.name, version: m.version, runtime: m.runtime, kind: m.kind, digest: current.digest, signer: current.signer, permissions: current.permissions, reference: m.reference });
  }

  async function trustKey() {
    const key = window.prompt("Public key of the plug-in author (minisign, the line after “untrusted comment”)");
    if (!key?.trim()) return;
    const id = await act("Trust key", () => invoke<string>("plugin_trust", { key: key.trim() }));
    if (id) project.audit("plugin", `trusted signing key ${id}`);
  }

  async function runChecks() {
    if (!current) return;
    const id = current.manifest.id;
    const out = await act(`Check values of ${id}`, () => invoke<{ results: CheckResult[] }>("plugin_check", { id, environment: envName }));
    if (out) checks[id] = out.results;
  }

  async function evaluate() {
    if (!current) return;
    const id = current.manifest.id;
    const values = await act(`Evaluate ${id}`, () => invoke<number[]>("plugin_predict", { id, temperature: [evalT], molarDensity: [evalRho], environment: envName }));
    evalOut = values ? values[0].toPrecision(6) : "";
  }

  async function revoke() {
    if (!current) return;
    await act(`Revoke ${current.manifest.id}`, () => invoke("plugin_revoke", { id: current!.manifest.id }));
  }

  async function remove() {
    if (!current || (await ask(`Remove ${current.manifest.name}?`, { title: "Remove plug-in", kind: "warning" })) !== true) return;
    const id = current.manifest.id;
    await act(`Remove ${id}`, () => invoke("plugin_remove", { id }));
    selected = null;
  }

  const close = () => (project.dialog = null);
</script>

<DialogFrame title="Plug-ins" width="1100px" height="640px" onclose={close}>
  <div class="row tabs">
    <button class:on={tab === "installed"} onclick={() => (tab = "installed")}>Installed ({plugins.length})</button>
    <button class:on={tab === "planned"} onclick={() => (tab = "planned")}>Planned add-ons</button>
    <button class:on={tab === "sdk"} onclick={() => (tab = "sdk")}>Developer kit</button>
  </div>
  {#if tab === "installed"}
    <div class="well list">
      <table class="grid">
        <thead><tr><th>Plug-in</th><th>Kind</th><th>Runs as</th><th>Package</th><th>Permissions</th><th>Check values</th></tr></thead>
        <tbody>
          {#each plugins as p (p.manifest.id)}
            <tr class="clickable" class:sel={selected === p.manifest.id} onclick={() => (selected = p.manifest.id)}>
              <td><b>{p.manifest.name}</b> {p.manifest.version}</td>
              <td>{p.manifest.kind}</td>
              <td>{runsAs(p.manifest.runtime)}</td>
              <td class:error={!!p.problem || p.signer.status === "untrusted"}>{p.problem ? "changed or invalid" : signerLabel(p.signer)}</td>
              <td class:ok={p.approved} class:muted={!p.approved}>{p.approved ? "approved" : "not approved: does not run"}</td>
              <td class:ok={verifiedLabel(checks[p.manifest.id]).startsWith("⛉")}>{verifiedLabel(checks[p.manifest.id])}</td>
            </tr>
          {:else}
            <tr><td colspan="6" class="muted">No plug-ins installed. Install one from a folder, or from the registry in Components.</td></tr>
          {/each}
        </tbody>
      </table>
    </div>
    {#if current}
      <div class="split2">
        <fieldset class="group">
          <legend>{current.manifest.name}</legend>
          <table class="props"><tbody>
            <tr><td>Description</td><td>{current.manifest.description}</td></tr>
            <tr><td>Method from</td><td>{current.manifest.reference || "—"}</td></tr>
            <tr><td>Licence</td><td>{current.manifest.license || "—"}</td></tr>
            <tr><td>Package</td><td class="mono">{current.digest.slice(0, 24)}…</td></tr>
            {#if current.problem}<tr><td>Problem</td><td class="error">{current.problem}</td></tr>{/if}
          </tbody></table>
          {#if current.manifest.kind === "model" && current.approved}
            <div class="row">
              T <input class="field num" type="number" bind:value={evalT} aria-label="Temperature K" /> K
              ρ <input class="field num" type="number" bind:value={evalRho} aria-label="Molar density" /> mol/m³
              <button class="btn" onclick={evaluate} disabled={busy}>Evaluate</button>
              <span class="mono">{evalOut}</span>
            </div>
          {/if}
          {#if checks[current.manifest.id]}
            <table class="grid small"><thead><tr><th>T / K</th><th>Expected</th><th>Plug-in</th><th>Dev. / %</th><th>Source</th></tr></thead><tbody>
              {#each checks[current.manifest.id] as r, i (i)}
                <tr><td>{r.check.temperature}</td><td>{r.check.expected.toPrecision(5)}</td><td>{r.value.toPrecision(5)}</td><td class:ok={r.pass} class:error={!r.pass}>{(100 * r.rel_dev).toFixed(3)}</td><td>{r.check.source}</td></tr>
              {/each}
            </tbody></table>
          {/if}
        </fieldset>
        <fieldset class="group">
          <legend>Permissions {current.approved ? "(approved)" : "(requested)"}</legend>
          <ul class="perms">{#each current.permissions as p (p)}<li>✓ {p}</li>{/each}<li class="muted">✗ anything else: denied</li></ul>
        </fieldset>
      </div>
    {/if}
  {:else if tab === "planned"}
    <div class="well list">
      <table class="grid">
        <thead><tr><th>Add-on (planned)</th><th>What it will do</th><th>Runs as</th></tr></thead>
        <tbody>{#each PLANNED as a (a.name)}<tr><td><b>{a.name}</b></td><td>{a.what}</td><td>{a.runs}</td></tr>{/each}</tbody>
      </table>
    </div>
    <p class="muted">Add-ons are implemented from published methods and open data only, and published as signed plug-ins.</p>
  {:else}
    <div class="sdk">
      <p><b>A new model is one file, its tests and a manifest.</b> Templates in the repository: <span class="mono">plugins/templates/python-model</span> (Python, runs in the project environment) and <span class="mono">plugins/templates/wasm-model</span> (WebAssembly, sandboxed).</p>
      <ol>
        <li>Copy a template; set <span class="mono">id</span>, <span class="mono">name</span> and the permissions you need in <span class="mono">plugin.toml</span> (nothing is granted that is not declared).</li>
        <li>Implement the model and list published check values (<span class="mono">[[check]]</span> with their source).</li>
        <li>Run the check-value harness: <span class="mono">propbench plugin check &lt;folder&gt;</span> (WASM) or <span class="mono">pytest &lt;folder&gt;</span> (Python).</li>
        <li>Sign: <span class="mono">propbench plugin keygen me</span>, then <span class="mono">propbench plugin sign &lt;folder&gt; --key me.key</span>; share <span class="mono">me.pub</span>.</li>
      </ol>
    </div>
  {/if}
  <p class="muted" role="status">{status}</p>
  {#snippet footer()}
    <button class="btn" onclick={installFolder} disabled={busy || !inTauri()}>Install from folder…</button>
    <button class="btn" onclick={trustKey} disabled={busy || !inTauri()}>Trust a key…</button>
    <span class="spacer"></span>
    {#if current && tab === "installed"}
      {#if !current.approved && !current.problem}<button class="btn" onclick={approveCurrent} disabled={busy}>Approve…</button>{/if}
      {#if current.approved}<button class="btn" onclick={runChecks} disabled={busy}>Run check values</button><button class="btn" onclick={revoke} disabled={busy}>Revoke</button>{/if}
      <button class="btn" onclick={remove} disabled={busy}>Remove</button>
    {/if}
    <button class="btn default" onclick={close}>Close</button>
  {/snippet}
</DialogFrame>

<style>
  .tabs {
    gap: 2px;
  }
  .tabs button {
    padding: 2px 10px;
  }
  .tabs .on {
    font-weight: 700;
  }
  .list {
    height: 220px;
    overflow: auto;
  }
  .split2 {
    display: grid;
    grid-template-columns: minmax(0, 3fr) minmax(0, 2fr);
    gap: 8px;
    margin-top: 6px;
  }
  .perms {
    margin: 0;
    padding-left: 16px;
  }
  .num {
    width: 72px;
  }
  .small {
    font-size: 10px;
  }
  .sdk {
    padding: 4px 8px;
    line-height: 1.6;
  }
</style>
