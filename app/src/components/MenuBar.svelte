<script lang="ts">
  // Classic menu bar (File, Edit, View, Data, Models, Validate, Report, Tools, Window, Help).
  import type { MenuItem } from "../lib/menu";

  interface Props {
    menus: { label: string; items: MenuItem[] }[];
  }
  let { menus }: Props = $props();
  let open = $state<string | null>(null);

  function choose(item: MenuItem) {
    if (item.disabled || item.separator) return;
    open = null;
    item.action?.();
  }
</script>

<svelte:window onclick={() => (open = null)} onkeydown={(e) => e.key === "Escape" && (open = null)} />

<nav class="menubar" aria-label="Main menu">
  {#each menus as m (m.label)}
    <div class="menu">
      <button
        class="title"
        class:on={open === m.label}
        aria-haspopup="menu"
        aria-expanded={open === m.label}
        onclick={(e) => {
          e.stopPropagation();
          open = open === m.label ? null : m.label;
        }}
        onmouseenter={() => open !== null && (open = m.label)}
      >
        <u>{m.label[0]}</u>{m.label.slice(1)}
      </button>
      {#if open === m.label}
        <div class="drop" role="menu">
          {#each m.items as item, i (i)}
            {#if item.separator}
              <div class="sep" role="separator"></div>
            {:else}
              <button
                role="menuitem"
                class="item"
                disabled={item.disabled}
                title={item.note ?? ""}
                onclick={(e) => {
                  e.stopPropagation();
                  choose(item);
                }}
              >
                {item.label}{#if item.note}<span class="note">{item.note}</span>{/if}
              </button>
            {/if}
          {/each}
        </div>
      {/if}
    </div>
  {/each}
</nav>

<style>
  .menubar {
    display: flex;
    gap: 0;
    padding: 1px 2px;
  }
  .menu {
    position: relative;
  }
  .title {
    padding: 2px 7px;
    background: none;
    border: 1px solid transparent;
  }
  .title:hover,
  .title.on {
    border-color: var(--hilite) var(--shadow) var(--shadow) var(--hilite);
  }
  .title.on {
    border-color: var(--shadow) var(--hilite) var(--hilite) var(--shadow);
  }
  .drop {
    position: absolute;
    top: 100%;
    left: 0;
    z-index: 20;
    min-width: 230px;
    padding: 2px;
    background: var(--face);
    border: 1px solid;
    border-color: var(--hilite) var(--dark) var(--dark) var(--hilite);
    box-shadow: 1px 1px 0 var(--shadow);
  }
  .item {
    display: flex;
    justify-content: space-between;
    gap: 16px;
    width: 100%;
    padding: 3px 18px;
    text-align: left;
    white-space: nowrap;
    background: none;
    border: 0;
  }
  .item:hover:not(:disabled) {
    color: var(--navy-text);
    background: var(--navy);
  }
  .item:disabled {
    color: var(--shadow);
  }
  .note {
    font-size: 10px;
    color: var(--shadow);
  }
  .sep {
    margin: 3px 2px;
    border-top: 1px solid var(--shadow);
    border-bottom: 1px solid var(--hilite);
  }
</style>
