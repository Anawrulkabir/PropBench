// AI proposals (CLAUDE.md AI rules): a reply's proposed changes are kept as pending data. A change is applied only
// through `apply` with an explicit confirmation that saw the exact preview, and the applied artefact carries its
// provenance (prompt, provider, model, version/time). Nothing else in the app applies AI output.

export interface Proposal {
  id: number;
  kind: "script" | "plot" | "mapping";
  title: string;
  content: string;
  value?: unknown;
  invalid?: string;
}

export interface Provenance {
  provider: string;
  model: string;
  base_url: string;
  prompt: string;
  time: number;
}

export interface Reply {
  text: string;
  proposals: Proposal[];
  provenance: Provenance;
}

export interface Pending extends Proposal {
  key: string;
  provenance: Provenance;
}

/** A change to make, with the provenance to store alongside it. */
export interface Change {
  kind: Proposal["kind"];
  title: string;
  content: string;
  value?: unknown;
  provenance: Provenance;
}

export class ProposalQueue {
  pending: Pending[] = [];

  receive(reply: Reply) {
    for (const p of reply.proposals) {
      this.pending.push({ ...p, key: `${reply.provenance.time}-${p.id}`, provenance: reply.provenance });
    }
  }

  /** The exact text the user confirms before a change is applied. */
  preview(key: string): string | null {
    const p = this.pending.find((x) => x.key === key);
    if (!p) return null;
    return `Apply this ${p.kind} proposed by ${p.provenance.provider} (${p.provenance.model})?\n\n${p.title}\n\n${p.content}`;
  }

  /** Remove the proposal and return the change only if `confirm` (shown the preview) returns true. */
  async apply(key: string, confirm: (preview: string) => boolean | Promise<boolean>): Promise<Change | null> {
    const p = this.pending.find((x) => x.key === key);
    const preview = this.preview(key);
    if (!p || preview === null || p.invalid) return null;
    if ((await confirm(preview)) !== true) return null;
    this.pending = this.pending.filter((x) => x.key !== key);
    return { kind: p.kind, title: p.title, content: p.content, value: p.value, provenance: p.provenance };
  }

  discard(key: string) {
    this.pending = this.pending.filter((x) => x.key !== key);
  }
}

/** A script header recording where AI-generated code came from (stored with the artefact, CLAUDE.md). */
export function provenanceHeader(c: Change): string {
  const when = new Date(c.provenance.time * 1000).toISOString();
  const prompt = c.provenance.prompt.split("\n").slice(-3).join(" ").slice(0, 200);
  return `# AI-generated, reviewed and applied by the user (${when})\n# provider: ${c.provenance.provider}, model: ${c.provenance.model}, endpoint: ${c.provenance.base_url}\n# prompt: ${prompt}\n`;
}
