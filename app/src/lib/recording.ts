// GUI action recording (README §4d): model labels as Python identifiers for recorded scripts.

/** A Python identifier for a model label. */
export function pyName(label: string): string {
  const s = label.toLowerCase().replace(/[^a-z0-9]+/g, "_").replace(/^_+|_+$/g, "");
  return /^[a-z_]/.test(s) ? s || "model" : `m_${s}`;
}
