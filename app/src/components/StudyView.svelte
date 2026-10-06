<script lang="ts">
  import { project } from "../lib/project.svelte";
  import { pct } from "../lib/quantities";
  import { freeParameters, physicsPassed } from "../lib/study";

  const METHODS = [
    { id: "loso", label: "Leave one source (dataset) out" },
    { id: "loto", label: "Leave one isotherm out" },
    { id: "kfold", label: "k-fold" },
    { id: "bootstrap", label: "Bootstrap (out-of-bag)" },
  ];
  const METRICS = [
    { id: "cv_aard", label: "cross-validation AARD" },
    { id: "cv_rms", label: "cross-validation RMS" },
    { id: "fit_aard", label: "fit AARD (all data)" },
    { id: "aic", label: "AIC" },
    { id: "bic", label: "BIC" },
  ];
  const PHYSICS = [
    "Finite, positive, continuous at zero density (dilute-gas limit)",
    "Increases with density on isotherms (dense fluid)",
    "Liquid value decreases with temperature on isobars",
    "Sane extrapolation 20 % beyond the data (no sign change, no jumps)",
  ];

  const locked = $derived(project.locked !== null);

  function toggleMethod(id: string, on: boolean) {
    const set = new Set(project.settings.methods);
    if (on) set.add(id);
    else set.delete(id);
    project.settings.methods = METHODS.map((m) => m.id).filter((m) => set.has(m));
    if (!set.has(project.rule.validation) && !locked && project.settings.methods.length) {
      project.rule.validation = project.settings.methods[0];
    }
  }

  function state(id: string): string {
    const c = project.candidate(id);
    if (!c) return "";
    if (project.busy && project.busy.endsWith(c.label)) return "running";
    if (c.study) return physicsPassed(c.study) === false ? "done · physics violation" : "done";
    if (c.fit) return "fitted";
    return "queued";
  }
</script>

<div class="view">
  <div class="cols">
    <fieldset class="group">
      <legend>1. Models</legend>
      {#each project.candidates as c (c.id)}
        <div class="row line">ƒ {c.label} <span class="muted">({freeParameters(c).length} free parameters)</span></div>
      {:else}
        <p class="muted">No candidates yet — add models on the Fit tab.</p>
      {/each}
    </fieldset>

    <fieldset class="group">
      <legend>2. Validation</legend>
      {#each METHODS as m (m.id)}
        <label class="row line">
          <input
            type="checkbox"
            checked={project.settings.methods.includes(m.id)}
            onchange={(e) => toggleMethod(m.id, (e.currentTarget as HTMLInputElement).checked)}
            disabled={locked && m.id === project.rule.validation}
          />
          {m.label}
          {#if m.id === "kfold"}<input class="field num small" type="number" min="2" bind:value={project.settings.k} aria-label="k" />{/if}
          {#if m.id === "bootstrap"}
            <input class="field num small" type="number" min="1" max="2000" bind:value={project.settings.nBootstrap} aria-label="Bootstrap samples" />
          {/if}
        </label>
      {/each}
      <div class="form">
        <label for="seed">Random seed</label>
        <input id="seed" class="field num" type="number" min="0" bind:value={project.settings.seed} />
        <label for="workers">Worker processes</label>
        <input id="workers" class="field num" type="number" min="1" max="64" bind:value={project.settings.workers} />
      </div>
    </fieldset>

    <fieldset class="group">
      <legend>3. Physics checks (applied to every model)</legend>
      {#each PHYSICS as p (p)}
        <div class="row line"><input type="checkbox" checked disabled /> {p}</div>
      {/each}
    </fieldset>

    <fieldset class="group">
      <legend>4. Selection rule</legend>
      <div class="form">
        <label for="metric">Rank by</label>
        <select id="metric" class="field" bind:value={project.rule.metric} disabled={locked}>
          {#each METRICS as m (m.id)}<option value={m.id}>{m.label}</option>{/each}
        </select>
        <label for="val">Validation</label>
        <select id="val" class="field" bind:value={project.rule.validation} disabled={locked}>
          {#each project.settings.methods as m (m)}<option value={m}>{m}</option>{/each}
        </select>
        <label for="tie">Tie rule</label>
        <div class="row">
          prefer fewer parameters within
          <input id="tie" class="field num small" type="number" min="0" max="99" step="1"
            value={Math.round(project.rule.tie_tolerance * 100)}
            onchange={(e) => (project.rule.tie_tolerance = Number((e.currentTarget as HTMLInputElement).value) / 100)}
            disabled={locked}
          /> %
        </div>
        <label for="phys">Reject if</label>
        <label class="row"><input id="phys" type="checkbox" bind:checked={project.rule.require_physics} disabled={locked} /> any physics violation</label>
      </div>
      {#if project.locked}
        <div class="notice row">
          🔒 Rule locked at {project.locked.at} before fitting ({project.locked.sha256.slice(0, 12)}…). Changing it starts a new study.
          <span class="spacer"></span>
          <button class="btn" onclick={() => project.unlockRule()}>Unlock</button>
        </div>
      {:else}
        <div class="row">
          <span class="muted">The rule is fixed (hashed) before any fit, so it cannot be chosen after seeing results.</span>
          <span class="spacer"></span>
          <button class="btn" onclick={() => project.lockRule()} disabled={!!project.busy}>Lock rule</button>
        </div>
      {/if}
    </fieldset>
  </div>

  <div class="row">
    <b>Run queue</b>
    <span class="muted">· {project.settings.workers} worker process{project.settings.workers > 1 ? "es" : ""}</span>
    <span class="spacer"></span>
    <button class="btn" onclick={() => project.select()} disabled={!!project.busy || !locked}>Select</button>
    <button
      class="btn default"
      onclick={() => project.runStudy()}
      disabled={!!project.busy || !project.candidates.length || !project.settings.methods.length}
    >
      {project.busy ? "Running…" : "Run all"}
    </button>
  </div>
  <div class="well">
    <table class="grid">
      <thead><tr><th>Model</th><th>State</th>{#each project.settings.methods as m (m)}<th>{m.toUpperCase()} AARD %</th>{/each}<th>Physics</th></tr></thead>
      <tbody>
        {#each project.candidates as c (c.id)}
          <tr>
            <td>{c.label}</td>
            <td class:ok={state(c.id).startsWith("done")} class:warn={state(c.id) === "running"}>{state(c.id)}</td>
            {#each project.settings.methods as m (m)}
              <td class="num">{pct(c.study?.cross_validation[m]?.pooled.aard)}</td>
            {/each}
            <td class:ok={physicsPassed(c.study) === true} class:error={physicsPassed(c.study) === false}>
              {physicsPassed(c.study) === null ? "–" : physicsPassed(c.study) ? "passed" : "violations"}
            </td>
          </tr>
        {:else}
          <tr><td colspan="9" class="muted">No candidates.</td></tr>
        {/each}
      </tbody>
    </table>
  </div>
</div>

<style>
  .view {
    display: flex;
    flex-direction: column;
    gap: 8px;
    height: 100%;
    min-height: 0;
    overflow: auto;
  }
  .cols {
    display: grid;
    grid-template-columns: repeat(2, minmax(0, 1fr));
    gap: 8px;
  }
  .cols fieldset {
    display: grid;
    gap: 4px;
    align-content: start;
  }
  .line {
    min-height: 19px;
  }
  .form {
    display: grid;
    grid-template-columns: auto 1fr;
    gap: 5px 8px;
    align-items: center;
    margin-top: 4px;
  }
  .small {
    width: 56px;
  }
</style>
