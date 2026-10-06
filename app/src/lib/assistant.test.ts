// README M4b acceptance: an AI-proposed change is never applied without confirmation.
import { describe, expect, it } from "vitest";
import { ProposalQueue, provenanceHeader, type Reply } from "./assistant";

const reply: Reply = {
  text: "Here is a script.",
  proposals: [
    { id: 0, kind: "script", title: "Global fit", content: "import propbench as pb\nprint(1)" },
    { id: 1, kind: "mapping", title: "mapping", content: "{not json", invalid: "the proposed JSON could not be read" },
  ],
  provenance: { provider: "anthropic", model: "model-x", base_url: "https://api.anthropic.com/v1/messages", prompt: "fit both", time: 1700000000 },
};

describe("AI proposals", () => {
  it("are never applied without an explicit confirmation", async () => {
    const q = new ProposalQueue();
    q.receive(reply);
    const key = q.pending[0].key;
    let shown = "";
    expect(await q.apply(key, (p) => ((shown = p), false))).toBeNull();
    expect(shown).toContain("import propbench as pb"); // the user saw the exact change
    expect(q.pending).toHaveLength(2); // still pending, nothing applied
    expect(await q.apply(key, () => "yes" as unknown as boolean)).toBeNull(); // only a literal true confirms
    expect(await q.apply("unknown", () => true)).toBeNull();
    const change = await q.apply(key, async () => true);
    expect(change?.content).toBe("import propbench as pb\nprint(1)");
    expect(q.pending).toHaveLength(1);
  });

  it("refuses invalid proposals even when confirmed, and records provenance", async () => {
    const q = new ProposalQueue();
    q.receive(reply);
    expect(await q.apply(q.pending[1].key, () => true)).toBeNull();
    q.discard(q.pending[1].key);
    const change = await q.apply(q.pending[0].key, () => true);
    const header = provenanceHeader(change!);
    expect(header).toContain("provider: anthropic, model: model-x");
    expect(header).toContain("prompt: fit both");
  });
});
