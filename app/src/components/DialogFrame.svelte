<script lang="ts">
  // Modal dialog frame in the classic style (navy caption, 3-D border, footer buttons).
  import type { Snippet } from "svelte";

  interface Props {
    title: string;
    width?: string;
    height?: string;
    onclose: () => void;
    children: Snippet;
    footer?: Snippet;
  }
  let { title, width = "860px", height = "560px", onclose, children, footer }: Props = $props();
</script>

<svelte:window onkeydown={(e) => e.key === "Escape" && onclose()} />

<div class="backdrop" role="presentation">
  <div class="dialog" role="dialog" aria-modal="true" aria-label={title} style="width: min({width}, 96vw); height: min({height}, 92vh)">
    <header class="caption">
      <span>{title}</span>
      <button class="x" onclick={onclose} aria-label="Close">×</button>
    </header>
    <div class="content">{@render children()}</div>
    {#if footer}<footer class="row buttons">{@render footer()}</footer>{/if}
  </div>
</div>

<style>
  .backdrop {
    position: fixed;
    inset: 0;
    z-index: 10;
    display: grid;
    place-items: center;
    background: rgba(0, 0, 0, 0.15);
  }
  .dialog {
    display: flex;
    flex-direction: column;
    background: var(--face);
    border: 1px solid;
    border-color: var(--hilite) var(--dark) var(--dark) var(--hilite);
    box-shadow: 2px 2px 0 var(--shadow);
  }
  .caption {
    display: flex;
    align-items: center;
    padding: 3px 4px 3px 8px;
    font-weight: 700;
    color: #fff;
    background: var(--navy);
  }
  .caption span {
    flex: 1;
  }
  .x {
    width: 16px;
    height: 14px;
    padding: 0;
    line-height: 10px;
    background: var(--face);
    border: 1px solid;
    border-color: var(--hilite) var(--dark) var(--dark) var(--hilite);
  }
  .content {
    flex: 1;
    min-height: 0;
    padding: 10px 12px;
    overflow: auto;
  }
  .buttons {
    padding: 8px 12px;
    border-top: 1px solid var(--shadow);
    box-shadow: inset 0 1px 0 var(--hilite);
  }
  .buttons :global(.btn) {
    min-width: 84px;
  }
</style>
