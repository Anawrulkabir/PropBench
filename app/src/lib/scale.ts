// Text size (Settings › Appearance): a per-viewer preference kept in browser storage, applied to the root font size.

const KEY = "propbench.scale";
export const SCALES = [90, 100, 110, 125, 150];

export function loadScale(): number {
  try {
    const v = Number(localStorage.getItem(KEY) ?? "100");
    return SCALES.includes(v) ? v : 100;
  } catch {
    return 100;
  }
}

export function applyScale(scale: number): void {
  document.documentElement.style.fontSize = `${(11 * scale) / 100}px`;
  try {
    localStorage.setItem(KEY, String(scale));
  } catch {
    /* storage unavailable: not remembered */
  }
}
