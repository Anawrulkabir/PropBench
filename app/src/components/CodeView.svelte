<script lang="ts">
  // Code and terminal (design/mockups/10_Code): the project's scripts, run in the project environment (separate
  // process, time and memory limits); the environment's packages and lock; the terminal. The AI assistant is M4b.
  import { errorMessage, worker } from "../lib/api";
  import { project } from "../lib/project.svelte";
  import { uniqueName } from "../lib/study";
  import TerminalPane from "./TerminalPane.svelte";

  interface RunResult {
    stdout: string;
    stderr: string;
    exit_code: number | null;
    timed_out: boolean;
    memory_exceeded: boolean;
    seconds: number;
  }

  let current = $state(Object.keys(project.scripts)[0] ?? "analysis.py");
  let tab = $state<"output" | "terminal">("output");
  let output = $state<RunResult | null>(null);
  let running = $state(false);
  let timeout = $state(600);
  let memory = $state(4096);
  let packages = $state("");
  let envBusy = $state<string | null>(null);
  let envMessage = $state("");

  const envName = $derived(project.name || "project");
  const names = $derived(Object.keys(project.scripts));
  $effect(() => {
    if (!project.scripts[current] && names.length) current = names[0];
  });

  function newScript() {
    const name = uniqueName(names, "script.py");
    project.scripts[name] = "import propbench as pb\n\ndata = pb.datasets()\nprint([d.name for d in data])\n";
    current = name;
  }

  function renameScript() {
    const name = window.prompt("Script name", current)?.trim();
    if (!name || name === current || project.scripts[name] !== undefined) return;
    const text = project.scripts[current];
    delete project.scripts[current];
    project.scripts[name.endsWith(".py") ? name : `${name}.py`] = text;
    current = name.endsWith(".py") ? name : `${name}.py`;
  }

  function deleteScript() {
    if (names.length <= 1 || !window.confirm(`Delete ${current}?`)) return;
    delete project.scripts[current];
    current = Object.keys(project.scripts)[0];
  }

  async function run() {
    running = true;
    tab = "output";
    output = null;
    project.note(`Running ${current} in the project environment`);
    try {
      output = await worker<RunResult>("env.run", {
        project: envName,
        code: project.scripts[current],
        timeout,
        memory_mb: memory,
        datasets: project.activeDatasets(),
      });
      const how = output.timed_out ? "stopped at the time limit" : output.memory_exceeded ? "stopped at the memory limit" : `exit code ${output.exit_code}`;
      project.note(`${current}: ${how} after ${output.seconds.toFixed(1)} s`, output.exit_code === 0 ? "info" : "warn");
    } catch (err) {
      project.note(`${current} failed: ${errorMessage(err)}`, "error");
    } finally {
      running = false;
    }
  }

  async function envAction(label: string, step: () => Promise<{ lock: string }>) {
    envBusy = label;
    try {
      const res = await step();
      project.environment.lock = res.lock;
      envMessage = `${label}: done`;
      project.note(`Environment ${envName}: ${label.toLowerCase()}`);
    } catch (err) {
      envMessage = `${label} failed: ${errorMessage(err)}`;
      project.note(envMessage, "error");
    } finally {
      envBusy = null;
    }
  }

  function install() {
    const list = packages.split(/[\s,]+/).filter(Boolean);
    if (!list.length) return;
    envAction(`Install ${list.join(", ")}`, async () => {
      const res = await worker<{ lock: string }>("env.install", { project: envName, packages: list });
      project.environment.packages = [...new Set([...project.environment.packages, ...list])];
      packages = "";
      return res;
    });
  }

  function syncFromLock() {
    envAction("Recreate from lock", () => worker<{ lock: string }>("env.sync", { project: envName, lock: project.environment.lock }));
  }

  function onKey(e: KeyboardEvent) {
    if ((e.ctrlKey || e.metaKey) && e.key === "Enter") {
      e.preventDefault();
      if (!running) run();
    } else if (e.key === "Tab") {
      e.preventDefault();
      const el = e.currentTarget as HTMLTextAreaElement;
      const { selectionStart: a, selectionEnd: b } = el;
      project.scripts[current] = project.scripts[current].slice(0, a) + "    " + project.scripts[current].slice(b);
      requestAnimationFrame(() => el.setSelectionRange(a + 4, a + 4));
    }
  }
</script>

<div class="code">
  <div class="files well">
    <div class="head">Scripts</div>
    {#each names as n (n)}
      <button class="file" class:sel={n === current} onclick={() => (current = n)}>{n}</button>
    {/each}
    <div class="row tools">
      <button class="btn" onclick={newScript}>New</button>
      <button class="btn" onclick={renameScript}>Rename</button>
      <button class="btn" onclick={deleteScript} disabled={names.length <= 1}>Delete</button>
    </div>
    <div class="head">Environment</div>
    <div class="muted small">{envName.toLowerCase().replace(/[^a-z0-9]+/g, "-")} (app data folder)</div>
    <input class="field" placeholder="packages, e.g. lmfit==1.3.2" bind:value={packages} onkeydown={(e) => e.key === "Enter" && install()} aria-label="Packages to install" />
    <div class="row tools">
      <button class="btn" onclick={install} disabled={!!envBusy || !packages.trim()}>Install</button>
      <button class="btn" onclick={syncFromLock} disabled={!!envBusy || !project.environment.lock}>Recreate from lock</button>
    </div>
    <div class="muted small">{envBusy ? `${envBusy}…` : envMessage}</div>
    <div class="head">Lock ({project.environment.lock.split("\n").filter(Boolean).length} packages)</div>
    <pre class="lock mono">{project.environment.lock || "(core packages only)"}</pre>
  </div>
  <div class="editor-col">
    <div class="row">
      <button class="btn default" onclick={run} disabled={running}>{running ? "Running…" : "▷ Run in project environment"}</button>
      <label class="row">Time limit <input class="field num" type="number" min="1" bind:value={timeout} /> s</label>
      <label class="row">Memory <input class="field num" type="number" min="64" step="64" bind:value={memory} /> MB</label>
      <span class="spacer"></span>
      <span class="muted">Ctrl+Enter runs · scripts are saved with the project</span>
    </div>
    <textarea class="field editor mono" bind:value={project.scripts[current]} onkeydown={onKey} spellcheck="false" aria-label="Script editor"></textarea>
    <div class="tabs">
      <button class:on={tab === "output"} onclick={() => (tab = "output")}>Output</button>
      <button class:on={tab === "terminal"} onclick={() => (tab = "terminal")}>Terminal</button>
    </div>
    <div class="bottom">
      {#if tab === "output"}
        <div class="out mono">
          {#if running}<div class="dim">Running {current}…</div>
          {:else if output}
            <pre>{output.stdout}</pre>
            {#if output.stderr}<pre class="err">{output.stderr}</pre>{/if}
            <div class="dim">
              {output.timed_out ? "Stopped at the time limit" : output.memory_exceeded ? "Stopped at the memory limit" : `Exit code ${output.exit_code}`} · {output.seconds.toFixed(2)} s
            </div>
          {:else}<div class="dim">Run a script: it runs in the project environment, in its own process, with the limits above.</div>{/if}
        </div>
      {:else}
        <TerminalPane project={envName} />
      {/if}
    </div>
  </div>
  <aside class="ai">
    <div class="head">AI assistant</div>
    <div class="notice">Planned for M4b. AI output never changes code or data without your confirmation, and keys stay in the OS keychain.</div>
  </aside>
</div>

<style>
  .code {
    display: grid;
    grid-template-columns: 220px minmax(0, 1fr) 200px;
    gap: 6px;
    height: 100%;
    min-height: 0;
  }
  .files {
    display: flex;
    flex-direction: column;
    gap: 3px;
    padding: 4px;
    overflow: auto;
  }
  .head {
    margin-top: 6px;
    font-weight: 700;
  }
  .file {
    padding: 2px 6px;
    text-align: left;
    background: none;
    border: none;
  }
  .file.sel {
    color: #fff;
    background: var(--navy);
  }
  .tools {
    gap: 3px;
  }
  .small {
    font-size: 10px;
  }
  .lock {
    max-height: 160px;
    margin: 0;
    overflow: auto;
    font-size: 10px;
    white-space: pre-wrap;
  }
  .editor-col {
    display: grid;
    grid-template-rows: auto minmax(0, 1fr) auto 200px;
    gap: 4px;
    min-height: 0;
  }
  .num {
    width: 64px;
  }
  .editor {
    min-height: 0;
    padding: 6px;
    font-size: 12px;
    line-height: 1.5;
    resize: none;
  }
  .tabs {
    display: flex;
    gap: 2px;
  }
  .tabs button {
    padding: 2px 10px;
  }
  .tabs .on {
    font-weight: 700;
  }
  .bottom {
    min-height: 0;
  }
  .out {
    height: 100%;
    padding: 6px;
    overflow: auto;
    color: #cfe;
    background: #111;
  }
  .out pre {
    margin: 0;
    white-space: pre-wrap;
  }
  .err {
    color: #f99;
  }
  .dim {
    color: #8a8;
  }
  .ai {
    display: grid;
    gap: 6px;
    align-content: start;
  }
</style>
