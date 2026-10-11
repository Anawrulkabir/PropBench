// Project history settings (README §4d): where to push, and whether every save commits the Git mirror.
export interface GithubSettings {
  clientId: string;
  repo: string;
  branch: string;
  commitOnSave: boolean;
}

export function loadGithub(): GithubSettings {
  const fallback: GithubSettings = { clientId: "", repo: "", branch: "main", commitOnSave: true };
  try {
    return { ...fallback, ...JSON.parse(localStorage.getItem("propbench.github") ?? "{}") };
  } catch {
    return fallback;
  }
}

/** "owner/repo" split, or null when it is not of that form. */
export function splitRepo(text: string): { owner: string; repo: string } | null {
  const m = /^\s*([A-Za-z0-9_-][A-Za-z0-9_.-]*)\/([A-Za-z0-9_.-]+)\s*$/.exec(text);
  if (!m || m[2] === "." || m[2] === "..") return null;
  return { owner: m[1], repo: m[2] };
}
