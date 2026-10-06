<script lang="ts">
  // Project history (README §4d): commits of the project's Git mirror (no Git install needed) and push to GitHub.
  import { invoke } from "@tauri-apps/api/core";
  import { errorMessage, inTauri } from "../lib/api";
  import { loadGithub, splitRepo } from "../lib/history";
  import { project } from "../lib/project.svelte";
  import DialogFrame from "./DialogFrame.svelte";

  interface Commit {
    id: string;
    message: string;
    author: string;
    time: number;
  }

  let commits = $state<Commit[]>([]);
  let message = $state("");
  let status = $state("");
  let busy = $state(false);
  const github = loadGithub();

  async function refresh() {
    if (!inTauri()) {
      status = "The project history runs in the desktop app.";
      return;
    }
    try {
      commits = await invoke<Commit[]>("history_list", { path: project.filePath, name: project.name });
    } catch (err) {
      status = errorMessage(err);
    }
  }
  $effect(() => {
    refresh();
  });

  async function commitNow() {
    busy = true;
    try {
      const done = await invoke<Commit | null>("history_commit", {
        path: project.filePath,
        message: message.trim() || `Update ${project.name}`,
        project: project.content(),
      });
      status = done ? `Committed ${done.id.slice(0, 8)}: ${done.message}` : "Nothing changed since the last commit";
      message = "";
      await refresh();
    } catch (err) {
      status = errorMessage(err);
    } finally {
      busy = false;
    }
  }

  async function push() {
    const target = splitRepo(github.repo);
    if (!target) {
      status = "Set the repository (owner/repository) in Settings › GitHub";
      return;
    }
    busy = true;
    try {
      const res = await invoke<{ commit: string; url: string; files: number }>("github_push", {
        ...target,
        branch: github.branch || "main",
        message: message.trim() || commits[0]?.message || `Update ${project.name}`,
        project: project.content(),
      });
      status = `Pushed ${res.files} files to ${github.repo} (${res.commit.slice(0, 8)})`;
      project.audit("github", `pushed to ${github.repo}@${github.branch}`);
    } catch (err) {
      status = errorMessage(err);
    } finally {
      busy = false;
    }
  }

  const close = () => (project.dialog = null);
</script>

<DialogFrame title="Project history" width="720px" height="520px" onclose={close}>
  <p class="muted">{project.filePath ? `Git repository next to ${project.filePath}` : "Save the project to keep its history next to the file (unsaved projects use the app data folder)."}</p>
  <div class="well list">
    <table class="grid">
      <thead><tr><th>Commit</th><th>When</th><th>Message</th></tr></thead>
      <tbody>
        {#each commits as c (c.id)}<tr><td class="mono">{c.id.slice(0, 8)}</td><td>{new Date(c.time * 1000).toLocaleString()}</td><td>{c.message}</td></tr>{:else}<tr><td colspan="3" class="muted">No commits yet.</td></tr>{/each}
      </tbody>
    </table>
  </div>
  <div class="row"><input class="field grow" bind:value={message} placeholder="What changed? (commit message)" aria-label="Commit message" /></div>
  <p class="muted" role="status">{busy ? "Working…" : status}</p>
  {#snippet footer()}
    <span class="muted">GitHub: {github.repo || "not set"}</span>
    <span class="spacer"></span>
    <button class="btn" onclick={commitNow} disabled={busy}>Commit</button>
    <button class="btn" onclick={push} disabled={busy || !github.repo}>Push to GitHub</button>
    <button class="btn default" onclick={close}>Close</button>
  {/snippet}
</DialogFrame>

<style>
  .list {
    height: 280px;
    overflow: auto;
  }
  .grow {
    flex: 1;
  }
</style>
