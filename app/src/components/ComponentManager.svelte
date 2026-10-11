<script lang="ts">
  // Component manager (design/mockups/04_Components, README §2b): bundled parts, the registry's components and the
  // installed ones. Installing downloads the archive, checks size and SHA-256 and unpacks it into the app data
  // folder (the worker's `components.*` operations); offline installation takes an archive file.
  import { errorMessage, fileToBase64, worker } from "../lib/api";
  import { project } from "../lib/project.svelte";
  import type { Dataset } from "../lib/types";
  import DialogFrame from "./DialogFrame.svelte";

  interface Entry {
    id: string;
    name: string;
    version: string;
    kind: string;
    category?: string;
    description?: string;
    license?: string;
    source?: string;
    size?: number;
    sha256?: string;
    requires?: string[];
  }
  interface Listing {
    registry: string;
    registry_error: string | null;
    installed: Entry[];
    available: Entry[];
    updates: Entry[];
  }
  interface Row {
    key: string;
    name: string;
    contents: string;
    source: string;
    status: string;
    category: string;
    version: string;
    kind: string;
    checksum: string;
    installed: boolean;
    installable: boolean;
    builtIn: boolean;
  }

  const BUILT_IN: Row[] = [
    ["core", "Core and calculator", "Calculator, plots, projects, fitting and validation", "PropBench (MIT)", "Core"],
    ["coolprop", "CoolProp fluid library", "Reference equations of state and transport correlations", "CoolProp (MIT)", "Thermodynamic engines"],
    ["nist", "NIST reference transport models", "NISTIR 8209 models with their check values", "NIST (public domain)", "Reference transport models"],
    ["feos", "FeOs engine", "PC-SAFT and entropy-scaling transport", "FeOs (MIT/Apache-2.0)", "Thermodynamic engines"],
  ].map(([key, name, contents, source, category]) => ({
    key, name, contents, source, category, status: "Bundled", version: "", kind: "", checksum: "part of the app",
    installed: true, installable: false, builtIn: true,
  }));
  const PLANNED: Row[] = [
    ["mixtures", "Mixture toolkit", "Mixing rules, binary parameter fitting", "PropBench", "Mixtures", "Planned (2.0)"],
    ["refprop", "REFPROP connector", "Uses your own installed REFPROP (never bundled)", "requires a licence", "Connectors", "Planned"],
  ].map(([key, name, contents, source, category, status]) => ({
    key, name, contents, source, category, status, version: "", kind: "", checksum: "",
    installed: false, installable: false, builtIn: true,
  }));

  function loadRegistry(): string {
    try {
      return localStorage.getItem("propbench.registry") ?? "";
    } catch {
      return "";
    }
  }
  let registry = $state(loadRegistry());
  let listing = $state<Listing | null>(null);
  let busy = $state<string | null>(null);
  let message = $state("");
  let category = $state("All components");
  let search = $state("");
  let picked = $state("core");
  let fileInput = $state<HTMLInputElement | null>(null);

  function rowOf(e: Entry, installed: boolean, update: Entry | undefined): Row {
    return {
      key: e.id,
      name: e.name,
      contents: e.description ?? "",
      source: e.source || e.license || "",
      category: e.category || { data: "Experimental data", parameters: "Fluid parameter sets", "reference-models": "Reference transport models", python: "Python packages" }[e.kind] || "Other",
      status: installed ? (update ? `Update ${update.version}` : `Installed ${e.version}`) : "Available",
      version: e.version,
      kind: e.kind,
      checksum: e.sha256 ? `SHA-256 ${e.sha256.slice(0, 16)}…` : "",
      installed,
      installable: !installed || !!update,
      builtIn: false,
    };
  }

  const rows = $derived.by(() => {
    const out: Row[] = [...BUILT_IN];
    const installed = new Map((listing?.installed ?? []).map((e) => [e.id, e]));
    const updates = new Map((listing?.updates ?? []).map((e) => [e.id, e]));
    for (const e of installed.values()) out.push(rowOf(e, true, updates.get(e.id)));
    const seen = new Set<string>();
    for (const e of listing?.available ?? []) {
      if (installed.has(e.id) || seen.has(e.id)) continue;
      seen.add(e.id);
      out.push(rowOf(e, false, undefined));
    }
    return [...out, ...PLANNED];
  });
  const categories = $derived(["All components", ...new Set(rows.map((r) => r.category))]);
  const shown = $derived(
    rows.filter((r) => (category === "All components" || r.category === category) && `${r.name} ${r.contents}`.toLowerCase().includes(search.toLowerCase())),
  );
  const current = $derived(rows.find((r) => r.key === picked));

  async function refresh() {
    busy = "Reading registry";
    try {
      listing = await worker<Listing>("components.list", { registry: registry.trim() || null });
      message = listing.registry_error ? `Registry not reachable (${listing.registry_error}); installed components still work.` : `Registry: ${listing.registry}`;
    } catch (err) {
      message = errorMessage(err);
    } finally {
      busy = null;
    }
  }

  $effect(() => {
    try {
      localStorage.setItem("propbench.registry", registry);
    } catch {
      /* not remembered */
    }
  });
  $effect(() => {
    refresh();
  });

  async function act(label: string, step: () => Promise<string>) {
    busy = label;
    try {
      message = await step();
      project.note(message);
      await refresh();
    } catch (err) {
      message = `${label} failed: ${errorMessage(err)}`;
      project.note(message, "error");
    } finally {
      busy = null;
    }
  }

  function install() {
    const r = current;
    if (!r || !r.installable) return;
    act(`Installing ${r.name}`, async () => {
      const res = await worker<{ installed: Entry[] }>("components.install", { id: r.key, registry: registry.trim() || null });
      return res.installed.length ? `Installed ${res.installed.map((e) => `${e.name} ${e.version}`).join(", ")} (checksums verified)` : `${r.name} is up to date`;
    });
  }

  function remove() {
    const r = current;
    if (!r || r.builtIn || !r.installed) return;
    act(`Removing ${r.name}`, async () => {
      await worker("components.remove", { id: r.key });
      return `Removed ${r.name}`;
    });
  }

  async function fromFile(e: Event) {
    const file = (e.currentTarget as HTMLInputElement).files?.[0];
    if (!file) return;
    await act(`Installing ${file.name}`, async () => {
      const res = await worker<{ installed: Entry[] }>("components.install_file", { content_base64: await fileToBase64(file) });
      return `Installed ${res.installed[0].name} ${res.installed[0].version} from ${file.name}`;
    });
    if (fileInput) fileInput.value = "";
  }

  function addData() {
    act("Adding published data", async () => {
      const res = await worker<{ datasets: Dataset[] }>("components.datasets");
      const n = await project.addDatasets(res.datasets, "component");
      return n ? `Added ${n} published datasets to the project` : "All published datasets are already in the project";
    });
  }

  const close = () => (project.dialog = null);
</script>

<DialogFrame title="Component Manager" width="1040px" height="640px" onclose={close}>
  <div class="split">
    <div class="well list">
      {#each categories as c (c)}<button class="item" class:sel={category === c} onclick={() => (category = c)}>🗀 {c}</button>{/each}
    </div>
    <div class="pane">
      <div class="row">
        <span>Search:</span><input class="field grow" bind:value={search} aria-label="Search components" />
        <span>Registry:</span>
        <input class="field reg" bind:value={registry} placeholder="default PropBench registry" aria-label="Registry URL" />
        <button class="btn" onclick={refresh} disabled={!!busy}>Refresh</button>
      </div>
      <div class="well table">
        <table class="grid">
          <thead><tr><th></th><th>Component</th><th>Contents</th><th>Source</th><th>Status</th></tr></thead>
          <tbody>
            {#each shown as r (r.key)}
              <tr class="clickable" class:sel={picked === r.key} onclick={() => (picked = r.key)}>
                <td><input type="checkbox" checked={r.installed} disabled aria-label="installed" /></td>
                <td>{r.name}</td><td>{r.contents}</td><td>{r.source}</td>
                <td class:ok={r.installed} class:link={r.installable}>{r.status}</td>
              </tr>
            {/each}
          </tbody>
        </table>
      </div>
      {#if current}
        <fieldset class="group">
          <legend>Details: {current.name}</legend>
          <table class="props"><tbody>
            <tr><td>Contents</td><td>{current.contents}</td></tr>
            <tr><td>Source</td><td>{current.source}</td></tr>
            {#if current.version}<tr><td>Version</td><td>{current.version} ({current.kind})</td></tr>{/if}
            <tr><td>Checksum</td><td>{current.checksum || "verified at download"}</td></tr>
          </tbody></table>
        </fieldset>
      {/if}
      <p class="muted msg" role="status">{busy ? `${busy}…` : message}</p>
    </div>
  </div>
  {#snippet footer()}
    <span class="muted">Components are installed in the app data folder only; size and SHA-256 are checked before unpacking.</span>
    <span class="spacer"></span>
    <input bind:this={fileInput} type="file" accept=".zip" class="hidden" onchange={fromFile} aria-label="Component archive" />
    <button class="btn" onclick={() => fileInput?.click()} disabled={!!busy}>Install from file…</button>
    <button class="btn" onclick={addData} disabled={!!busy || !(listing?.installed ?? []).some((e) => e.kind === "data")}>Add published data</button>
    <button class="btn" onclick={remove} disabled={!!busy || !current || current.builtIn || !current.installed}>Remove</button>
    <button class="btn" onclick={install} disabled={!!busy || !current?.installable}>{current?.installed ? "Update" : "Install selected"}</button>
    <button class="btn default" onclick={close}>Close</button>
  {/snippet}
</DialogFrame>

<style>
  .split {
    display: grid;
    grid-template-columns: 220px minmax(0, 1fr);
    gap: 8px;
    height: 100%;
  }
  .list {
    display: flex;
    flex-direction: column;
    padding: 4px;
    overflow: auto;
  }
  .item {
    padding: 3px 6px;
    text-align: left;
    background: none;
    border: none;
  }
  .item.sel {
    color: #fff;
    background: var(--navy);
  }
  .pane {
    display: grid;
    grid-template-rows: auto minmax(0, 1fr) auto auto;
    gap: 6px;
    min-height: 0;
  }
  .table {
    overflow: auto;
  }
  .reg {
    width: 260px;
  }
  .grow {
    flex: 1;
  }
  .ok {
    color: var(--ok);
  }
  .link {
    color: #1f3c9a;
  }
  .hidden {
    display: none;
  }
  .msg {
    min-height: 1.4em;
    margin: 0;
  }
</style>
