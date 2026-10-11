<script lang="ts">
  // Report generator (README §2, M4): the project's results as PDF, Word or Markdown, or a reproducibility bundle.
  // The worker writes the document and recomputes the reference models' check values for it.
  import { errorMessage, worker } from "../lib/api";
  import { deviationPlot, propertyPlot, stateMap } from "../lib/figures";
  import { project } from "../lib/project.svelte";
  import { toContent } from "../lib/projectfile";
  import { display } from "../lib/quantities";
  import DialogFrame from "./DialogFrame.svelte";

  let title = $state(`${project.name}: data, models and validation`);
  let authors = $state("");
  let template = $state("elsevier");
  let format = $state<"pdf" | "docx" | "md" | "zip">("pdf");
  let preset = $state("elsevier2");
  let withFigures = $state(true);
  let busy = $state(false);
  let message = $state("");

  function spec() {
    const datasets = project.activeDatasets();
    const unit = display(datasets[0]?.quantity ?? "viscosity");
    const fitted = project.candidates.filter((c) => c.fit);
    const figures = withFigures
      ? [
          { caption: "Measured states of the datasets.", spec: stateMap(datasets, preset) },
          { caption: "Measured values with expanded uncertainties.", spec: propertyPlot(datasets, unit, preset) },
          ...fitted.map((c) => ({ caption: `Relative deviations of the data from ${c.label}.`, spec: deviationPlot(c.fit!.points, c.label, unit, preset) })),
        ]
      : [];
    return {
      title,
      authors: authors.split(",").map((a) => a.trim()).filter(Boolean),
      template,
      seed: project.settings.seed,
      project: { name: project.name },
      datasets,
      consistency: project.consistency,
      models: fitted.map((c) => ({ label: c.label, reference: c.start.reference, summary: c.fit?.summary, study: c.study })),
      comparison: project.comparison,
      selection: project.selection && project.locked ? { ...project.selection, sha256: project.locked.sha256, rule: project.locked.rule } : null,
      references: (project.tools.references as { key: string; citation: string }[]) ?? [],
      figures,
    };
  }

  async function generate() {
    busy = true;
    message = "";
    try {
      const res = await worker<{ content_base64: string; mime: string; bytes: number }>("report.render", {
        spec: spec(),
        format,
        project: format === "zip" ? toContent(project.savedState(), null, []) : null,
      });
      const bin = atob(res.content_base64);
      const bytes = new Uint8Array(bin.length);
      for (let i = 0; i < bin.length; i++) bytes[i] = bin.charCodeAt(i);
      const url = URL.createObjectURL(new Blob([bytes], { type: res.mime }));
      const a = document.createElement("a");
      a.href = url;
      a.download = `${project.name.replace(/[^\w-]+/g, "_")}-report.${format}`;
      a.click();
      setTimeout(() => URL.revokeObjectURL(url), 1000);
      message = `Report written (${(res.bytes / 1024).toFixed(0)} kB)`;
      project.note(`Report generated: ${format.toUpperCase()}, ${(res.bytes / 1024).toFixed(0)} kB`);
      project.audit("report", `${format} (${template})`);
    } catch (err) {
      message = errorMessage(err);
    } finally {
      busy = false;
    }
  }

  const close = () => (project.dialog = null);
</script>

<DialogFrame title="Generate report" width="620px" height="460px" onclose={close}>
  <div class="form">
    <label for="r-title">Title</label><input id="r-title" class="field" bind:value={title} />
    <label for="r-authors">Authors</label><input id="r-authors" class="field" bind:value={authors} placeholder="comma-separated" />
    <label for="r-tpl">Template</label>
    <select id="r-tpl" class="field" bind:value={template}><option value="elsevier">Elsevier</option><option value="acs">ACS</option><option value="plain">Plain</option></select>
    <label for="r-fmt">Format</label>
    <select id="r-fmt" class="field" bind:value={format}>
      <option value="pdf">PDF</option><option value="docx">Word (.docx)</option><option value="md">Markdown</option>
      <option value="zip">Reproducibility bundle (.zip: report, figures, inputs, versions)</option>
    </select>
    <label for="r-preset">Figure size</label>
    <select id="r-preset" class="field" bind:value={preset}><option value="elsevier1">1 column</option><option value="elsevier2">2 columns</option></select>
    <span></span><label class="row"><input type="checkbox" bind:checked={withFigures} /> Include figures (states, data, deviations of each fitted model)</label>
  </div>
  <fieldset class="group">
    <legend>Contents</legend>
    <ul>
      <li>Data: {project.datasets.length} datasets with sources and uncertainties</li>
      <li>Consistency: {project.consistency ? `${project.consistency.overlaps.length} overlaps` : "not run"}</li>
      <li>Models: {project.candidates.filter((c) => c.fit).length} fitted, {project.candidates.filter((c) => c.study).length} validated</li>
      <li>Comparison: {project.comparison ? "included" : "not run"} · selection: {project.selection ? project.selection.chosen : "none"}</li>
      <li>Reference models' check values (recomputed now) and versions, seeds</li>
    </ul>
  </fieldset>
  <p class="muted" role="status">{busy ? "Writing the report…" : message}</p>
  {#snippet footer()}
    <span class="spacer"></span>
    <button class="btn default" onclick={generate} disabled={busy || !project.datasets.length}>Generate</button>
    <button class="btn" onclick={close}>Close</button>
  {/snippet}
</DialogFrame>

<style>
  .form {
    display: grid;
    grid-template-columns: auto 1fr;
    gap: 5px 8px;
    align-items: center;
    margin-bottom: 8px;
  }
  ul {
    margin: 4px 0;
    padding-left: 18px;
  }
</style>
