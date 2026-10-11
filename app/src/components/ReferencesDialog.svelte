<script lang="ts">
  // References (README §2e.10): BibTeX import/export, DOI lookup (Crossref, needs network), and attaching a
  // reference to a dataset's provenance (citation and DOI).
  import { errorMessage, worker } from "../lib/api";
  import { project } from "../lib/project.svelte";
  import DialogFrame from "./DialogFrame.svelte";

  interface Ref {
    key: string;
    type: string;
    fields: Record<string, string>;
    citation: string;
  }

  let doi = $state("");
  let bibtex = $state("");
  let message = $state("");
  let busy = $state(false);
  let picked = $state<string | null>(null);
  let target = $state(project.datasets[0]?.name ?? "");
  const refs = $derived(project.tools.references as Ref[]);
  const current = $derived(refs.find((r) => r.key === picked));

  function add(list: Ref[]) {
    const keys = new Set(refs.map((r) => r.key));
    let n = 0;
    for (const r of list) {
      if (keys.has(r.key)) continue;
      project.tools.references.push(r);
      keys.add(r.key);
      n++;
    }
    message = `${n} reference${n === 1 ? "" : "s"} added${list.length > n ? ` (${list.length - n} already in the project)` : ""}`;
  }

  async function lookup() {
    busy = true;
    try {
      const res = await worker<{ reference: Ref }>("refs.doi", { doi });
      add([res.reference]);
      picked = res.reference.key;
      doi = "";
    } catch (err) {
      message = errorMessage(err);
    } finally {
      busy = false;
    }
  }

  async function importBib() {
    busy = true;
    try {
      const res = await worker<{ references: Ref[] }>("refs.parse", { bibtex });
      add(res.references);
      bibtex = "";
    } catch (err) {
      message = errorMessage(err);
    } finally {
      busy = false;
    }
  }

  async function exportBib() {
    const res = await worker<{ bibtex: string }>("refs.format", { references: refs.map(({ key, type, fields }) => ({ key, type, fields })) });
    const url = URL.createObjectURL(new Blob([res.bibtex], { type: "application/x-bibtex" }));
    const a = document.createElement("a");
    a.href = url;
    a.download = `${project.name.replace(/[^\w-]+/g, "_")}.bib`;
    a.click();
    URL.revokeObjectURL(url);
  }

  function attach() {
    const d = project.datasets.find((x) => x.name === target);
    if (!d || !current) return;
    d.provenance = { ...d.provenance, citation: current.citation, doi: current.fields.doi ?? d.provenance.doi };
    project.audit("reference", `${current.key} → ${d.name}`);
    message = `${current.key} attached to ${d.name}`;
  }

  const close = () => (project.dialog = null);
</script>

<DialogFrame title="References" width="900px" height="600px" onclose={close}>
  <div class="refs">
    <div class="list well">
      {#each refs as r (r.key)}
        <button class="item" class:sel={picked === r.key} onclick={() => (picked = r.key)}><b>{r.key}</b><br /><span class="muted">{r.citation}</span></button>
      {:else}<p class="muted">No references yet.</p>{/each}
    </div>
    <div class="side">
      <fieldset class="group">
        <legend>Add by DOI (Crossref)</legend>
        <div class="row"><input class="field grow" bind:value={doi} placeholder="10.1007/s10765-024-03332-4" aria-label="DOI" /><button class="btn" onclick={lookup} disabled={busy || !doi.trim()}>Look up</button></div>
      </fieldset>
      <fieldset class="group">
        <legend>Import BibTeX</legend>
        <textarea class="field mono bib" bind:value={bibtex} placeholder="@article{'{'}key, author = ..., title = ..., doi = ...{'}'}" aria-label="BibTeX"></textarea>
        <div class="row end"><button class="btn" onclick={importBib} disabled={busy || !bibtex.trim()}>Import</button></div>
      </fieldset>
      {#if current}
        <fieldset class="group">
          <legend>{current.key}</legend>
          <table class="props"><tbody>{#each Object.entries(current.fields) as [k, v] (k)}<tr><td>{k}</td><td>{v}</td></tr>{/each}</tbody></table>
          <div class="row">
            Attach to <select class="field" bind:value={target}>{#each project.datasets as d (d.name)}<option>{d.name}</option>{/each}</select>
            <button class="btn" onclick={attach} disabled={!project.datasets.length}>Attach</button>
            <span class="spacer"></span>
            <button class="btn" onclick={() => { project.tools.references = refs.filter((r) => r.key !== current?.key); picked = null; }}>Remove</button>
          </div>
        </fieldset>
      {/if}
      <p class="muted" role="status">{busy ? "Working…" : message}</p>
    </div>
  </div>
  {#snippet footer()}
    <span class="muted">References are saved with the project and listed in reports.</span>
    <span class="spacer"></span>
    <button class="btn" onclick={exportBib} disabled={!refs.length}>Export BibTeX…</button>
    <button class="btn default" onclick={close}>Close</button>
  {/snippet}
</DialogFrame>

<style>
  .refs {
    display: grid;
    grid-template-columns: 1fr 1fr;
    gap: 8px;
    height: 100%;
  }
  .list {
    overflow: auto;
    padding: 4px;
  }
  .item {
    display: block;
    width: 100%;
    padding: 4px 6px;
    text-align: left;
    background: none;
    border: none;
    border-bottom: 1px solid var(--shadow);
  }
  .item.sel {
    background: var(--select);
  }
  .side {
    display: grid;
    gap: 6px;
    align-content: start;
  }
  .grow {
    flex: 1;
  }
  .bib {
    width: 100%;
    height: 110px;
  }
  .end {
    justify-content: flex-end;
  }
</style>
