<script lang="ts">
  // Code editor (README §4d): Monaco with Python highlighting, loaded on first use. Falls back to a plain text
  // area while loading or if Monaco cannot start.
  interface Props {
    value: string;
    onchange: (value: string) => void;
    onrun?: () => void;
  }
  let { value, onchange, onrun }: Props = $props();

  let host = $state<HTMLDivElement | null>(null);
  let ready = $state(false);
  let failed = $state(false);
  let editor: { getValue(): string; setValue(v: string): void; dispose(): void } | null = null;

  $effect(() => {
    if (!host) return;
    let disposed = false;
    (async () => {
      try {
        // core editor and the Python grammar only (no language-service workers)
        const [monaco, { default: EditorWorker }] = await Promise.all([
          import("monaco-editor/editor/editor.api"),
          import("monaco-editor/editor/editor.worker?worker"),
          import("monaco-editor/languages/definitions/python/register"),
        ]);
        (self as unknown as { MonacoEnvironment: unknown }).MonacoEnvironment = { getWorker: () => new EditorWorker() };
        if (disposed || !host) return;
        const ed = monaco.editor.create(host, {
          value,
          language: "python",
          automaticLayout: true,
          minimap: { enabled: false },
          fontSize: 12,
          fontFamily: "IBM Plex Mono, Consolas, monospace",
          scrollBeyondLastLine: false,
          tabSize: 4,
          insertSpaces: true,
        });
        ed.onDidChangeModelContent(() => onchange(ed.getValue()));
        ed.addCommand(monaco.KeyMod.CtrlCmd | monaco.KeyCode.Enter, () => onrun?.());
        editor = ed;
        ready = true;
      } catch {
        failed = true;
      }
    })();
    return () => {
      disposed = true;
      editor?.dispose();
      editor = null;
    };
  });

  // Keep the editor in step when the script changes from outside (another file chosen, a proposal applied).
  $effect(() => {
    const v = value;
    if (editor && editor.getValue() !== v) editor.setValue(v);
  });
</script>

<div class="wrap">
  <div class="host" bind:this={host} class:hidden={!ready}></div>
  {#if !ready}
    <textarea class="field mono plain" value={value} oninput={(e) => onchange((e.currentTarget as HTMLTextAreaElement).value)} spellcheck="false" aria-label="Script editor" data-loading={!failed}></textarea>
  {/if}
</div>

<style>
  .wrap {
    position: relative;
    min-height: 0;
    height: 100%;
    border: 1px solid var(--shadow);
  }
  .host {
    position: absolute;
    inset: 0;
  }
  .hidden {
    visibility: hidden;
  }
  .plain {
    width: 100%;
    height: 100%;
    padding: 6px;
    font-size: 12px;
    line-height: 1.5;
    resize: none;
  }
</style>
