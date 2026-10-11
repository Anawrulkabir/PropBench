<script lang="ts">
  // AI assistant (README §4d): bring your own key (kept in the OS keychain by the shell, never shown again), see
  // exactly what is sent, and apply a proposed change only after confirming its preview.
  import { invoke } from "@tauri-apps/api/core";
  import { ask } from "@tauri-apps/plugin-dialog";
  import { errorMessage, inTauri } from "../lib/api";
  import { type Change, ProposalQueue, provenanceHeader, type Reply } from "../lib/assistant";
  import { project } from "../lib/project.svelte";
  import { uniqueName } from "../lib/study";

  interface Props {
    script: string;
    onscript: (name: string) => void;
  }
  let { script, onscript }: Props = $props();

  const PROVIDERS = [
    { id: "openai", label: "OpenAI-compatible", model: "gpt-4o-mini" },
    { id: "anthropic", label: "Anthropic", model: "claude-sonnet-5-5" },
    { id: "gemini", label: "Google Gemini", model: "gemini-2.5-flash" },
    { id: "groq", label: "Groq", model: "llama-3.3-70b-versatile" },
    { id: "openrouter", label: "OpenRouter", model: "openai/gpt-4o-mini" },
    { id: "together", label: "Together", model: "meta-llama/Llama-3.3-70B-Instruct-Turbo" },
    { id: "ollama", label: "Ollama (local)", model: "llama3.2" },
    { id: "lmstudio", label: "LM Studio (local)", model: "local-model" },
  ];
  function stored(key: string, fallback: string) {
    try {
      return localStorage.getItem(key) ?? fallback;
    } catch {
      return fallback;
    }
  }
  let provider = $state(stored("propbench.ai.provider", "openai"));
  let model = $state(stored(`propbench.ai.model.${stored("propbench.ai.provider", "openai")}`, PROVIDERS[0].model));
  let baseUrl = $state("");
  let hasKey = $state<boolean | null>(null);
  let question = $state("");
  let includeScript = $state(true);
  let includeResults = $state(true);
  let busy = $state(false);
  let error = $state("");
  let log = $state<{ role: "user" | "assistant"; content: string }[]>([]);
  const queue = new ProposalQueue();
  let pending = $state(queue.pending);
  const local = $derived(provider === "ollama" || provider === "lmstudio");

  $effect(() => {
    const p = provider;
    try {
      localStorage.setItem("propbench.ai.provider", p);
    } catch {
      /* not remembered */
    }
    if (!inTauri()) return;
    invoke<boolean>("secret_has", { name: `ai.${p}` })
      .then((v) => (hasKey = v))
      .catch(() => (hasKey = null));
  });

  function chooseProvider(id: string) {
    provider = id;
    model = stored(`propbench.ai.model.${id}`, PROVIDERS.find((p) => p.id === id)?.model ?? "");
  }

  async function setKey() {
    const key = window.prompt(`API key for ${PROVIDERS.find((p) => p.id === provider)?.label} (stored in the OS keychain)`);
    if (!key) return;
    try {
      await invoke("secret_set", { name: `ai.${provider}`, value: key });
      hasKey = true;
    } catch (err) {
      error = errorMessage(err);
    }
  }

  /** Exactly what is sent with the question (shown before sending). */
  const context = $derived.by(() => {
    const lines = [`Project: ${project.name}`];
    for (const d of project.datasets) lines.push(`Dataset ${d.name}: ${d.values.length} points of ${d.quantity} of ${d.fluid}, T ${Math.min(...d.temperature).toFixed(1)}–${Math.max(...d.temperature).toFixed(1)} K`);
    if (includeResults) {
      for (const c of project.candidates.filter((x) => x.fit)) lines.push(`Model ${c.label}: AARD ${c.fit?.summary.deviations.aard?.toFixed(3)} %`);
      for (const w of project.consistency?.warnings ?? []) lines.push(`Consistency warning: ${w}`);
    }
    if (includeScript && script) lines.push(`Current script:\n${script}`);
    return lines.join("\n");
  });

  async function send() {
    if (!question.trim()) return;
    busy = true;
    error = "";
    const messages = [...log, { role: "user" as const, content: question.trim() }];
    try {
      if (!inTauri()) throw new Error("the assistant runs in the desktop app");
      try {
        localStorage.setItem(`propbench.ai.model.${provider}`, model);
      } catch {
        /* not remembered */
      }
      const reply = await invoke<Reply>("assistant_ask", { provider, model, baseUrl: baseUrl.trim() || null, messages, context });
      log = [...messages, { role: "assistant", content: reply.text }];
      queue.receive(reply);
      pending = [...queue.pending];
      question = "";
    } catch (err) {
      error = errorMessage(err);
    } finally {
      busy = false;
    }
  }

  async function confirmPreview(text: string): Promise<boolean> {
    return inTauri() ? ask(text, { title: "Apply AI proposal?", kind: "warning" }) : window.confirm(text);
  }

  async function applyProposal(key: string) {
    const change: Change | null = await queue.apply(key, confirmPreview);
    pending = [...queue.pending];
    if (!change) return;
    if (change.kind === "script") {
      const name = uniqueName(Object.keys(project.scripts), `${change.title.replace(/[^\w-]+/g, "_").slice(0, 40) || "ai_script"}.py`);
      project.scripts[name] = provenanceHeader(change) + change.content + "\n";
      onscript(name);
    } else {
      const tools = project.tools as Record<string, unknown>;
      const list = (tools.aiProposals as unknown[]) ?? [];
      tools.aiProposals = [...list, change];
    }
    project.audit("ai", `${change.kind} "${change.title}" applied (${change.provenance.provider}, ${change.provenance.model})`);
    project.note(`AI proposal applied after confirmation: ${change.kind} "${change.title}"`);
  }
</script>

<aside class="ai">
  <div class="head">AI assistant</div>
  <div class="form">
    <select class="field" value={provider} onchange={(e) => chooseProvider((e.currentTarget as HTMLSelectElement).value)} aria-label="Provider">
      {#each PROVIDERS as p (p.id)}<option value={p.id}>{p.label}</option>{/each}
    </select>
    <input class="field" bind:value={model} aria-label="Model" placeholder="model" />
    <input class="field" bind:value={baseUrl} aria-label="Endpoint" placeholder="endpoint (optional)" />
    <div class="row">
      <span class="muted">{local ? "local, no key needed" : hasKey ? "key in keychain" : "no key"}</span>
      <span class="spacer"></span>
      {#if !local}<button class="btn" onclick={setKey}>{hasKey ? "Replace key" : "Add key"}</button>{/if}
    </div>
  </div>
  <div class="chat well">
    {#each log as m, i (i)}<div class="msg {m.role}">{m.content}</div>{/each}
    {#if !log.length}<div class="muted">Ask about your data, models or scripts. Proposed changes appear below and are applied only when you confirm.</div>{/if}
  </div>
  {#each pending as p (p.key)}
    <div class="proposal">
      <b>{p.kind}: {p.title}</b>
      <pre class="mono">{p.content}</pre>
      {#if p.invalid}<div class="err">{p.invalid}</div>{/if}
      <div class="row"><button class="btn default" onclick={() => applyProposal(p.key)} disabled={!!p.invalid}>Preview and apply…</button><button class="btn" onclick={() => { queue.discard(p.key); pending = [...queue.pending]; }}>Discard</button></div>
    </div>
  {/each}
  <details>
    <summary>What is sent ({context.length} characters)</summary>
    <label class="row"><input type="checkbox" bind:checked={includeScript} /> current script</label>
    <label class="row"><input type="checkbox" bind:checked={includeResults} /> fit results and warnings</label>
    <pre class="mono sent">{context}</pre>
    <p class="muted">Only this text and your question go to {PROVIDERS.find((p) => p.id === provider)?.label}. Measured values are not sent.</p>
  </details>
  <textarea class="field q" bind:value={question} placeholder="Ask about this project…" aria-label="Question"></textarea>
  <div class="row"><span class="err">{error}</span><span class="spacer"></span><button class="btn" onclick={send} disabled={busy || !question.trim()}>{busy ? "Waiting…" : "Send"}</button></div>
</aside>

<style>
  .ai {
    min-width: 0;
    display: flex;
    flex-direction: column;
    gap: 5px;
    min-height: 0;
    overflow: auto;
  }
  .head {
    font-weight: 700;
  }
  .form {
    display: grid;
    gap: 3px;
  }
  .chat {
    min-height: 80px;
    max-height: 260px;
    overflow: auto;
    padding: 4px;
  }
  .msg {
    margin-bottom: 4px;
    white-space: pre-wrap;
  }
  .msg.user {
    font-weight: 700;
  }
  .proposal {
    padding: 4px;
    background: #fffbe6;
    border: 1px solid var(--shadow);
  }
  .proposal pre,
  .sent {
    max-height: 140px;
    margin: 4px 0;
    overflow: auto;
    font-size: 10px;
    white-space: pre-wrap;
  }
  .q {
    height: 64px;
  }
  .err {
    color: var(--error);
  }
</style>
