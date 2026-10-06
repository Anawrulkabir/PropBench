<script lang="ts">
  // Settings (mockup 11), Component manager (mockup 04), Add-on manager (mockup 14) and About. Installing add-ons
  // (M4c), the AI assistant, GitHub and remote compute (M4b) are not built yet: their controls are
  // shown disabled. Credentials are never stored by the UI (CLAUDE.md: OS keychain only).
  import { invoke } from "@tauri-apps/api/core";
  import { errorMessage, inTauri, remoteConnect, remoteDisconnect, runOn } from "../lib/api";
  import { loadGithub } from "../lib/history";
  import { project } from "../lib/project.svelte";
  import { applyScale, loadScale, SCALES } from "../lib/scale";
  import ComponentManager from "./ComponentManager.svelte";
  import DialogFrame from "./DialogFrame.svelte";

  const close = () => (project.dialog = null);

  // --- AI keys and GitHub (README §4d) ---
  const AI_PROVIDERS = ["openai", "anthropic", "gemini", "groq", "openrouter", "together"];
  let aiKeys = $state<Record<string, boolean>>({});
  $effect(() => {
    if (!inTauri()) return;
    for (const p of AI_PROVIDERS) invoke<boolean>("secret_has", { name: `ai.${p}` }).then((v) => (aiKeys[p] = v)).catch(() => undefined);
    invoke<boolean>("secret_has", { name: "github.token" }).then((v) => (githubSigned = v)).catch(() => undefined);
  });
  async function forgetKey(p: string) {
    await invoke("secret_delete", { name: `ai.${p}` }).catch(() => undefined);
    aiKeys[p] = false;
  }
  let github = $state(loadGithub());
  let githubSigned = $state(false);
  let githubMessage = $state("");
  let deviceCode = $state<{ device_code: string; user_code: string; verification_uri: string; interval?: number } | null>(null);
  $effect(() => {
    try {
      localStorage.setItem("propbench.github", JSON.stringify(github));
    } catch {
      /* not remembered */
    }
  });
  async function signIn() {
    githubMessage = "";
    try {
      if (!inTauri()) throw new Error("sign-in runs in the desktop app");
      deviceCode = await invoke("github_signin_start", { clientId: github.clientId.trim() });
      const started = Date.now();
      while (deviceCode && Date.now() - started < 15 * 60_000) {
        await new Promise((r) => setTimeout(r, ((deviceCode?.interval ?? 5) + 1) * 1000));
        const status = await invoke<string>("github_signin_poll", { clientId: github.clientId.trim(), deviceCode: deviceCode?.device_code });
        if (status === "ok") {
          githubSigned = true;
          githubMessage = "Signed in to GitHub";
          break;
        }
      }
    } catch (err) {
      githubMessage = errorMessage(err);
    } finally {
      deviceCode = null;
    }
  }
  async function signOut() {
    await invoke("secret_delete", { name: "github.token" }).catch(() => undefined);
    githubSigned = false;
  }

  // --- remote compute (README §4d) ---
  function loadRemote() {
    try {
      return { host: "", user: "", port: null as number | null, identity: "", python: "", ...JSON.parse(localStorage.getItem("propbench.remote") ?? "{}") };
    } catch {
      return { host: "", user: "", port: null as number | null, identity: "", python: "" };
    }
  }
  let remote = $state(loadRemote());
  let remoteInfo = $state<{ propbench: string; python: string } | null>(runOn.host ? { propbench: "", python: "" } : null);
  let remoteBusy = $state(false);
  let remoteMessage = $state(runOn.host ? `Connected to ${runOn.host}` : "Not connected");
  let runRemote = $state(runOn.target === "remote");

  async function connectRemote() {
    remoteBusy = true;
    try {
      localStorage.setItem("propbench.remote", JSON.stringify(remote));
    } catch {
      /* not remembered */
    }
    try {
      if (!inTauri()) throw new Error("remote compute runs in the desktop app");
      const info = await remoteConnect({
        host: remote.host.trim(),
        user: remote.user.trim() || null,
        port: remote.port || null,
        identity: remote.identity.trim() || null,
        python: remote.python.trim(),
      });
      remoteInfo = info;
      runOn.host = remote.host.trim();
      remoteMessage = `Connected to ${runOn.host}: PropBench ${info.propbench}, Python ${info.python}, CoolProp ${info.coolprop}`;
      project.note(remoteMessage);
    } catch (err) {
      remoteMessage = `Connection failed: ${errorMessage(err)}`;
    } finally {
      remoteBusy = false;
    }
  }

  async function disconnectRemote() {
    await remoteDisconnect().catch(() => undefined);
    remoteInfo = null;
    runOn.host = "";
    setRunRemote(false);
    remoteMessage = "Not connected";
  }

  function setRunRemote(on: boolean) {
    runRemote = on;
    runOn.target = on ? "remote" : "local";
    project.runOn = on ? runOn.host : "";
  }

  // --- settings ---
  const SECTIONS = ["Environment", "AI assistant", "GitHub", "Remote compute", "Components", "Appearance"];
  let section = $state("Environment");
  let scale = $state(loadScale());
  $effect(() => applyScale(scale));

  // --- add-ons (README §2f) ---
  const ADDONS = [
    { name: "Data evaluation", what: "Recommended values with uncertainty from all available data", runs: "WASM", status: "verified", installed: "Available" },
    { name: "Property estimation", what: "Group contribution; PC-SAFT parameters from SMILES", runs: "Python", status: "verified", installed: "Available" },
    { name: "Binary parameter regression", what: "Fit mixture parameters to VLE and property data", runs: "Rust", status: "verified", installed: "Available" },
    { name: "VLE consistency tests", what: "Herington, Van Ness and point tests", runs: "WASM", status: "verified", installed: "Available" },
    { name: "Automatic equation search", what: "Symbolic regression (PySR)", runs: "Python", status: "community", installed: "Available" },
    { name: "Surface fitting", what: "η(T, p) and ρ(T, p) surfaces with 3D view", runs: "Rust", status: "verified", installed: "Available" },
    { name: "Advanced statistics", what: "ANOVA, robust regression, hypothesis tests", runs: "WASM", status: "verified", installed: "Available" },
    { name: "Uncertainty workbench", what: "GUM and Monte Carlo with report", runs: "WASM", status: "verified", installed: "Available" },
    { name: "Plot digitizer", what: "Data points from figures in PDFs and images", runs: "WASM", status: "community", installed: "Available" },
    { name: "Molecular simulation link", what: "LAMMPS, Green–Kubo viscosity; runs on a remote server", runs: "Python", status: "community", installed: "Available" },
  ];
  let addon = $state(ADDONS[4].name);
  let verifiedOnly = $state(false);
  const shownAddons = $derived(ADDONS.filter((a) => !verifiedOnly || a.status === "verified"));
</script>

{#if project.dialog === "settings"}
  <DialogFrame title="Settings – {section}" width="1000px" height="540px" onclose={close}>
    <div class="split">
      <div class="well list">
        {#each SECTIONS as s (s)}
          <button class="item" class:sel={section === s} onclick={() => (section = s)}>{s}</button>
        {/each}
      </div>
      <div class="pane">
        {#if section === "Environment"}
          <fieldset class="group">
            <legend>Project environment</legend>
            <div class="form">
              <span>Location</span><span class="mono">app data / envs / {project.name.toLowerCase().replace(/\s+/g, "-")}</span>
              <span>Python</span><span class="mono">3.12 (bundled, managed by uv)</span>
              <span>Storage limit</span><select class="field" disabled><option>5 GB</option></select>
              <span>Script limits</span><span class="mono">time 10 min, memory 4 GB</span>
            </div>
            <label class="row"><input type="checkbox" checked disabled /> Never modify system Python or PATH (always on)</label>
            <p class="muted">Per-project environments and limits: M1c.</p>
          </fieldset>
        {:else if section === "AI assistant"}
          <fieldset class="group">
            <legend>AI assistant</legend>
            <p>The assistant is in Tools › Code and terminal. Choose a provider there; keys are kept in the OS keychain and are never shown again or written to project files.</p>
            <div class="form">
              <span>Stored keys</span>
              <span>{#each AI_PROVIDERS as p (p)}<button class="btn" onclick={() => forgetKey(p)} disabled={!aiKeys[p]}>Forget {p}</button> {/each}</span>
            </div>
            <p class="muted">Before anything is sent, the panel shows exactly which text goes to the provider; measured values are not sent. AI output never changes code or data without your confirmation, and every applied change records the prompt, provider and model.</p>
          </fieldset>
        {:else if section === "GitHub"}
          <fieldset class="group">
            <legend>GitHub</legend>
            <div class="form">
              <span>Account</span><span>{githubSigned ? "signed in (token in the OS keychain)" : "not signed in"}</span>
              <label for="gh-client">OAuth app client id</label><input id="gh-client" class="field" bind:value={github.clientId} placeholder="client id of PropBench's GitHub OAuth app" />
              <label for="gh-repo">Repository</label><input id="gh-repo" class="field" bind:value={github.repo} placeholder="owner/repository" />
              <label for="gh-branch">Branch</label><input id="gh-branch" class="field" bind:value={github.branch} placeholder="main" />
            </div>
            <label class="row"><input type="checkbox" bind:checked={github.commitOnSave} /> Commit the project history on every save</label>
            {#if deviceCode}<p class="notice">Open <b>{deviceCode.verification_uri}</b> and enter <b class="mono">{deviceCode.user_code}</b>. Waiting for GitHub…</p>{/if}
            <div class="row">
              <span class="muted">{githubMessage}</span><span class="spacer"></span>
              {#if githubSigned}<button class="btn" onclick={signOut}>Sign out</button>{/if}
              <button class="btn" onclick={signIn} disabled={!!deviceCode}>Sign in with GitHub</button>
            </div>
            <p class="muted">The history is an ordinary Git repository next to the project file (settings as text, data as CSV and JSON); File › Project history commits and pushes it. No Git installation is needed.</p>
          </fieldset>
        {:else if section === "Remote compute"}
          <fieldset class="group">
            <legend>Remote compute</legend>
            <div class="form">
              <label for="rm-host">Host</label><input id="rm-host" class="field" bind:value={remote.host} placeholder="gpu-server.example.org" />
              <label for="rm-user">User</label><input id="rm-user" class="field" bind:value={remote.user} placeholder="(from your SSH config)" />
              <label for="rm-port">Port</label><input id="rm-port" class="field" type="number" bind:value={remote.port} placeholder="22" />
              <label for="rm-key">SSH key file</label><input id="rm-key" class="field" bind:value={remote.identity} placeholder="(SSH agent)" />
              <label for="rm-py">Remote Python</label><input id="rm-py" class="field" bind:value={remote.python} placeholder="/opt/propbench/python/bin/python3" />
            </div>
            <div class="row">
              <button class="btn" onclick={connectRemote} disabled={remoteBusy || !remote.host || !remote.python}>{remoteBusy ? "Connecting…" : "Connect"}</button>
              <button class="btn" onclick={disconnectRemote} disabled={remoteBusy || !remoteInfo}>Disconnect</button>
              <label class="row"><input type="checkbox" checked={runRemote} onchange={(e) => setRunRemote((e.currentTarget as HTMLInputElement).checked)} disabled={!remoteInfo} /> Run fits and validation on the remote engine</label>
            </div>
            <p class:ok={!!remoteInfo} class="muted">{remoteMessage}</p>
            <p class="muted">Only over SSH with your keys (the system's OpenSSH, batch mode); nothing listens on the network. Fits, validation, comparisons and Monte Carlo run remotely; files, components and environments stay on this computer.</p>
          </fieldset>
        {:else if section === "Components"}
          <p>Components are managed in Tools › Components.</p>
          <button class="btn" onclick={() => (project.dialog = "components")}>Open the component manager</button>
        {:else}
          <fieldset class="group">
            <legend>Appearance</legend>
            <div class="form">
              <label for="st-scale">Text size</label>
              <select id="st-scale" class="field" bind:value={scale}>{#each SCALES as v (v)}<option value={v}>{v} %</option>{/each}</select>
              <span>Theme</span><span>Classic (as the design mockups)</span>
            </div>
          </fieldset>
        {/if}
      </div>
    </div>
    {#snippet footer()}
      <span class="spacer"></span>
      <button class="btn default" onclick={close}>OK</button>
      <button class="btn" onclick={close}>Cancel</button>
    {/snippet}
  </DialogFrame>
{:else if project.dialog === "components"}
  <ComponentManager />
{:else if project.dialog === "addons"}
  <DialogFrame title="Add-on Manager" width="1100px" height="620px" onclose={close}>
    <div class="row"><button class="btn">Available ({ADDONS.length})</button><span class="spacer"></span><label class="row"><input type="checkbox" bind:checked={verifiedOnly} /> Verified only</label></div>
    <div class="well">
      <table class="grid">
        <thead><tr><th>Add-on</th><th>What it does</th><th>Runs as</th><th>Status</th><th>Installed</th></tr></thead>
        <tbody>
          {#each shownAddons as a (a.name)}
            <tr class="clickable" class:sel={addon === a.name} onclick={() => (addon = a.name)}>
              <td><b>{a.name}</b></td><td>{a.what}</td><td>{a.runs}</td>
              <td class:ok={a.status === "verified"} class:muted={a.status !== "verified"}>{a.status === "verified" ? "⛉ verified" : "community"}</td>
              <td class="link">{a.installed}</td>
            </tr>
          {/each}
        </tbody>
      </table>
    </div>
    <div class="split2">
      <fieldset class="group">
        <legend>Details: {addon}</legend>
        <table class="props"><tbody>
          <tr><td>Runs as</td><td>{ADDONS.find((a) => a.name === addon)?.runs === "Python" ? "Python, in the project environment" : "sandboxed (WASM)"}</td></tr>
          <tr><td>Check-value tests</td><td>[status from registry]</td></tr>
          <tr><td>Signed by</td><td>[publisher key]</td></tr>
        </tbody></table>
      </fieldset>
      <fieldset class="group">
        <legend>Permissions requested (approve to install)</legend>
        <table class="grid"><tbody>
          <tr><td>✓ Read and write this project's data</td><td class="ok">requested</td></tr>
          <tr><td>✓ Compute: up to 4 threads, 4 GB memory</td><td class="ok">requested</td></tr>
          <tr><td>✗ Files outside the project folder</td><td class="error">not requested: denied</td></tr>
          <tr><td>✗ Network: any other host</td><td class="error">not requested: denied</td></tr>
        </tbody></table>
      </fieldset>
    </div>
    {#snippet footer()}
      <span class="muted">Signature checked before install. Add-ons from published methods and open data only. Plug-in system: M4c.</span>
      <span class="spacer"></span>
      <button class="btn" disabled>Developer kit…</button>
      <button class="btn" disabled>Approve and install</button>
      <button class="btn default" onclick={close}>Close</button>
    {/snippet}
  </DialogFrame>
{:else if project.dialog === "about"}
  <DialogFrame title="About PropBench" width="520px" height="320px" onclose={close}>
    <p><b>PropBench 0.1.0</b> — an open desktop workbench for thermophysical property models of new fluids.</p>
    <p>MIT licence. Science in a Python worker calling CoolProp, FeOs, NumPy and SciPy; Tauri shell.</p>
    <p class="muted">Reference models are implemented from the original publications (e.g. NISTIR 8209, Huber 2018) and verified against their check values.</p>
    {#snippet footer()}<span class="spacer"></span><button class="btn default" onclick={close}>OK</button>{/snippet}
  </DialogFrame>
{/if}

<style>
  .split {
    display: grid;
    grid-template-columns: 210px 1fr;
    gap: 10px;
    height: 100%;
  }
  .split2 {
    display: grid;
    grid-template-columns: 1fr 1fr;
    gap: 10px;
    margin-top: 8px;
  }
  .list {
    display: flex;
    flex-direction: column;
    padding: 4px;
  }
  .item {
    padding: 3px 6px;
    text-align: left;
    background: none;
    border: 0;
  }
  .item.sel {
    color: #fff;
    background: var(--navy);
  }
  .pane {
    display: grid;
    gap: 8px;
    align-content: start;
  }
  .form {
    display: grid;
    grid-template-columns: 130px 1fr;
    gap: 5px 8px;
    align-items: center;
    margin-bottom: 6px;
  }
  .link {
    color: var(--navy);
  }
</style>
