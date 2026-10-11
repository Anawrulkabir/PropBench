<script lang="ts">
  // Embedded terminal (README §4): the user's shell in the project environment (pb-term through Tauri), drawn with
  // xterm.js. Outside the desktop app (browser UI tests) it shows a note instead.
  import "@xterm/xterm/css/xterm.css";
  import { invoke } from "@tauri-apps/api/core";
  import { listen } from "@tauri-apps/api/event";
  import { FitAddon } from "@xterm/addon-fit";
  import { Terminal } from "@xterm/xterm";
  import { errorMessage, inTauri } from "../lib/api";

  interface Props {
    project: string;
  }
  let { project }: Props = $props();

  let host = $state<HTMLDivElement | null>(null);
  let status = $state(inTauri() ? "Starting the shell in the project environment…" : "The terminal runs in the desktop app.");

  $effect(() => {
    if (!host || !inTauri()) return;
    const term = new Terminal({ fontFamily: "IBM Plex Mono, Consolas, monospace", fontSize: 12, cursorBlink: true });
    const fit = new FitAddon();
    term.loadAddon(fit);
    term.open(host);
    fit.fit();
    let id: number | null = null;
    let stopped = false;
    const unlisten: (() => void)[] = [];
    const decoder = new TextDecoder();
    (async () => {
      unlisten.push(
        await listen<{ id: number; data: number[] }>("terminal-output", (e) => {
          if (e.payload.id === id) term.write(decoder.decode(new Uint8Array(e.payload.data), { stream: true }));
        }),
      );
      unlisten.push(
        await listen<{ id: number }>("terminal-exit", (e) => {
          if (e.payload.id === id) status = "The shell ended.";
        }),
      );
      try {
        id = await invoke<number>("terminal_open", { project, cols: term.cols, rows: term.rows });
        status = "";
        if (stopped) invoke("terminal_close", { id });
      } catch (err) {
        status = `Terminal failed: ${errorMessage(err)}`;
      }
    })();
    const input = term.onData((data) => {
      if (id !== null) invoke("terminal_write", { id, data }).catch(() => undefined);
    });
    const observer = new ResizeObserver(() => {
      fit.fit();
      if (id !== null) invoke("terminal_resize", { id, cols: term.cols, rows: term.rows }).catch(() => undefined);
    });
    observer.observe(host);
    return () => {
      stopped = true;
      observer.disconnect();
      input.dispose();
      for (const u of unlisten) u();
      if (id !== null) invoke("terminal_close", { id }).catch(() => undefined);
      term.dispose();
    };
  });
</script>

<div class="terminal">
  {#if status}<div class="status">{status}</div>{/if}
  <div class="host" bind:this={host}></div>
</div>

<style>
  .terminal {
    position: relative;
    display: flex;
    flex-direction: column;
    height: 100%;
    min-height: 0;
    background: #111;
  }
  .status {
    padding: 4px 6px;
    font-family: var(--mono);
    color: #8a8;
  }
  .host {
    flex: 1;
    min-height: 0;
    padding: 2px 4px;
  }
</style>
