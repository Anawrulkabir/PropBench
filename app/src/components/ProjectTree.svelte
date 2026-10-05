<script lang="ts">
  import { project } from "../lib/project.svelte";

  let open = $state({ datasets: true, models: true, studies: true });

  const studies = $derived(
    project.candidates.flatMap((c) =>
      Object.entries(c.study?.cross_validation ?? {}).map(([method, cv]) => ({
        key: `${c.id}-${method}`,
        label: `${method.toUpperCase()} · ${c.label}`,
        folds: cv.folds.length,
        id: c.id,
      })),
    ),
  );
</script>

<div class="tree well" role="tree" aria-label="Project">
  <div class="node root" role="treeitem" aria-selected="false" aria-expanded="true">
    <span class="icon">▣</span>{project.name}
  </div>

  <div class="node" role="treeitem" aria-selected="false" aria-expanded={open.datasets}>
    <button class="toggle" onclick={() => (open.datasets = !open.datasets)} aria-label="Toggle datasets">
      {open.datasets ? "−" : "+"}
    </button>
    <span class="icon">🗀</span>Datasets
  </div>
  {#if open.datasets}
    {#each project.datasets as d (d.name)}
      <button
        class="leaf"
        class:sel={project.selected?.type === "dataset" && project.selected.name === d.name}
        role="treeitem"
        aria-selected={project.selected?.type === "dataset" && project.selected.name === d.name}
        onclick={() => {
          project.selected = { type: "dataset", name: d.name };
          project.view = "data";
        }}
      >
        <span class="icon">▦</span><span class="name">{d.name}</span><span class="count">{d.values.length}</span>
      </button>
    {:else}
      <div class="leaf muted">(no data — Import)</div>
    {/each}
  {/if}

  <div class="node" role="treeitem" aria-selected="false" aria-expanded={open.models}>
    <button class="toggle" onclick={() => (open.models = !open.models)} aria-label="Toggle models">
      {open.models ? "−" : "+"}
    </button>
    <span class="icon">🗀</span>Models
  </div>
  {#if open.models}
    {#each project.candidates as c (c.id)}
      <button
        class="leaf"
        class:sel={project.selected?.type === "candidate" && project.selected.id === c.id}
        role="treeitem"
        aria-selected={project.selected?.type === "candidate" && project.selected.id === c.id}
        onclick={() => {
          project.selected = { type: "candidate", id: c.id };
          project.view = "fit";
        }}
      >
        <span class="icon fn">ƒ</span><span class="name">{c.label}</span>
        {#if project.selection?.chosen === c.label}<span class="count ok">✓</span>{/if}
      </button>
    {:else}
      <div class="leaf muted">(none)</div>
    {/each}
  {/if}

  <div class="node" role="treeitem" aria-selected="false" aria-expanded={open.studies}>
    <button class="toggle" onclick={() => (open.studies = !open.studies)} aria-label="Toggle studies">
      {open.studies ? "−" : "+"}
    </button>
    <span class="icon">🗀</span>Studies
  </div>
  {#if open.studies}
    {#each studies as s (s.key)}
      <button
        class="leaf"
        role="treeitem"
        aria-selected="false"
        onclick={() => {
          project.selected = { type: "candidate", id: s.id };
          project.view = "results";
        }}
      >
        <span class="icon">⟋</span><span class="name">{s.label}</span><span class="count">{s.folds}</span>
      </button>
    {:else}
      <div class="leaf muted">(none)</div>
    {/each}
  {/if}
</div>

<style>
  .tree {
    height: 100%;
    overflow: auto;
    padding: 4px 2px;
  }
  .node,
  .leaf {
    display: flex;
    align-items: center;
    gap: 4px;
    width: 100%;
    height: 18px;
    padding: 0 4px;
    background: none;
    border: 0;
    text-align: left;
    white-space: nowrap;
  }
  .node {
    padding-left: 4px;
  }
  .root {
    padding-left: 8px;
  }
  .leaf {
    padding-left: 40px;
  }
  .leaf.sel .name {
    color: var(--navy-text);
    background: var(--navy);
    outline: 1px dotted #fff;
  }
  .toggle {
    width: 11px;
    height: 11px;
    padding: 0;
    font-size: 9px;
    line-height: 9px;
    background: var(--field);
    border: 1px solid var(--shadow);
  }
  .icon {
    width: 14px;
    color: #6b5d2e;
    text-align: center;
  }
  .fn {
    color: var(--navy);
    font-style: italic;
  }
  .name {
    padding: 0 2px;
    overflow: hidden;
    text-overflow: ellipsis;
  }
  .count {
    margin-left: auto;
    padding-right: 6px;
    color: var(--muted);
  }
</style>
