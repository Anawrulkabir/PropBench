<script lang="ts">
  import { project } from "../lib/project.svelte";

  let tab = $state<"log" | "problems">("log");
  let box: HTMLDivElement | undefined = $state();
  const problems = $derived(project.log.filter((l) => l.level !== "info"));
  const shown = $derived(tab === "log" ? project.log : problems);

  $effect(() => {
    void shown.length;
    if (box) box.scrollTop = box.scrollHeight;
  });
</script>

<section class="output">
  <header class="titlebar">Output</header>
  <div class="tabs row">
    <button class="btn" class:active={tab === "log"} onclick={() => (tab = "log")}>Log</button>
    <button class="btn" class:active={tab === "problems"} onclick={() => (tab = "problems")}>
      Problems ({problems.length})
    </button>
  </div>
  <div class="lines well mono" bind:this={box} aria-live="polite">
    {#each shown as line, i (i)}
      <div class={line.level}>{line.time} {line.text}</div>
    {:else}
      <div class="muted">{tab === "log" ? "Ready." : "No problems."}</div>
    {/each}
  </div>
</section>

<style>
  .output {
    display: flex;
    flex-direction: column;
    height: 100%;
    min-height: 0;
  }
  .titlebar {
    padding: 2px 6px;
    font-weight: 700;
    color: #0a1a3a;
    background: var(--panel-title);
  }
  .tabs {
    padding: 3px 4px;
  }
  .tabs .btn {
    min-height: 19px;
    padding: 0 8px;
  }
  .tabs .btn.active {
    font-weight: 700;
  }
  .lines {
    flex: 1;
    min-height: 0;
    margin: 0 4px 4px;
    padding: 4px 6px;
    overflow: auto;
    white-space: pre-wrap;
  }
  .warn {
    color: var(--warn);
  }
  .error {
    color: var(--error);
  }
</style>
