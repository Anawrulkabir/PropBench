<script lang="ts">
  import { project } from "../lib/project.svelte";
  import { pct } from "../lib/quantities";
  import { physicsPassed, typicalUncertainty } from "../lib/study";
  import BarChart from "./BarChart.svelte";

  const methods = $derived(
    [...new Set(project.candidates.flatMap((c) => Object.keys(c.study?.cross_validation ?? {})))].sort(),
  );
  const ranked = $derived.by(() => {
    const order = project.selection?.ranking ?? [];
    const excluded = new Set(project.selection?.excluded ?? []);
    return [...project.candidates].sort((a, b) => {
      const ia = order.indexOf(a.label);
      const ib = order.indexOf(b.label);
      return (ia < 0 ? 1e9 : ia) - (ib < 0 ? 1e9 : ib) || a.label.localeCompare(b.label);
    }).map((c) => ({
      c,
      rank: order.indexOf(c.label) + 1,
      status:
        project.selection?.chosen === c.label
          ? "selected"
          : excluded.has(c.label)
            ? "rejected"
            : order.includes(c.label)
              ? "passes"
              : "–",
    }));
  });
  const focus = $derived(
    (project.selected?.type === "candidate" ? project.candidate(project.selected.id) : undefined) ??
      project.candidates.find((c) => c.label === project.selection?.chosen) ??
      project.candidates.find((c) => c.study),
  );
  const u = $derived(typicalUncertainty(project.datasets));
</script>

<div class="view">
  <div class="bar row">
    <b>Results</b>
    <span class="muted">
      · {project.candidates.length} candidates
      {#if project.locked}· rule: rank by {project.locked.rule.metric} ({project.locked.rule.validation}){project.locked.rule.require_physics ? ", reject physics violations" : ""}{/if}
    </span>
    <span class="spacer"></span>
    <button class="btn" onclick={() => (project.view = "study")}>Study setup</button>
  </div>

  {#if !project.candidates.some((c) => c.study)}
    <div class="empty well">No validation results yet — set up and run a study.</div>
  {:else}
    <div class="well">
      <table class="grid">
        <thead>
          <tr>
            <th>Rank</th><th>Model</th><th>Params</th>
            {#each methods as m (m)}<th>{m.toUpperCase()} %</th>{/each}
            <th>Fit AARD %</th><th>Physics</th><th>Status</th>
          </tr>
        </thead>
        <tbody>
          {#each ranked as { c, rank, status } (c.id)}
            <tr
              class="clickable"
              class:sel={focus?.id === c.id}
              class:rejected={status === "rejected"}
              onclick={() => (project.selected = { type: "candidate", id: c.id })}
            >
              <td class="num">{rank || "–"}</td>
              <td class:bold={status === "selected"}>{c.label}</td>
              <td class="num">{c.fit?.n_parameters ?? "–"}</td>
              {#each methods as m (m)}<td class="num">{pct(c.study?.cross_validation[m]?.pooled.aard)}</td>{/each}
              <td class="num">{pct(c.fit?.summary.deviations.aard)}</td>
              <td class="num">{c.study?.physics ? c.study.physics.filter((p) => !p.passed).length : "–"}</td>
              <td class:bold={status === "selected"} class:ok={status === "selected"}>{status}</td>
            </tr>
          {/each}
        </tbody>
      </table>
    </div>

    <div class="well plotbox">
      <BarChart
        groups={project.candidates.map((c) => ({
          label: c.label,
          values: methods.map((m) => c.study?.cross_validation[m]?.pooled.aard ?? null),
        }))}
        seriesNames={methods.map((m) => m.toUpperCase())}
        yLabel="cross-validation AARD (%)"
        reference={u === null ? null : { value: u, label: "median expanded uncertainty" }}
      />
    </div>

    {#if focus?.study}
      <div class="split">
        <fieldset class="group">
          <legend>Folds: {focus.label}</legend>
          {#each Object.entries(focus.study.cross_validation) as [method, cv] (method)}
            <div class="well folds">
              <table class="grid">
                <thead><tr><th>{method.toUpperCase()} fold</th><th>Test n</th><th>Test AARD %</th><th>Bias %</th><th>Train AARD %</th></tr></thead>
                <tbody>
                  {#each cv.folds as f (f.name)}
                    <tr class:rejected={!f.success}>
                      <td>{f.name}</td>
                      <td class="num">{f.test.n}</td>
                      <td class="num">{pct(f.test.aard)}</td>
                      <td class="num">{pct(f.test.bias)}</td>
                      <td class="num">{pct(f.train.aard)}</td>
                    </tr>
                  {/each}
                </tbody>
              </table>
            </div>
          {/each}
        </fieldset>
        <fieldset class="group">
          <legend>Physics checks: {focus.label}</legend>
          <table class="grid">
            <tbody>
              {#each focus.study.physics ?? [] as p (p.name)}
                <tr>
                  <td class:ok={p.passed} class:error={!p.passed}>{p.passed ? "✓" : "✗"}</td>
                  <td>{p.name}</td>
                  <td class="mono">{p.message}</td>
                </tr>
              {/each}
            </tbody>
          </table>
          <p class="muted">Overall: {physicsPassed(focus.study) ? "no violations" : "violations found"}</p>
        </fieldset>
      </div>
    {/if}
  {/if}
</div>

<style>
  .view {
    display: flex;
    flex-direction: column;
    gap: 6px;
    height: 100%;
    min-height: 0;
    overflow: auto;
  }
  .bold {
    font-weight: 700;
  }
  tr.rejected td {
    color: var(--error);
  }
  .plotbox {
    padding: 4px;
  }
  .split {
    display: grid;
    grid-template-columns: minmax(0, 1fr) minmax(0, 1fr);
    gap: 8px;
  }
  .folds {
    max-height: 220px;
    margin-bottom: 6px;
    overflow: auto;
  }
</style>
