// Unit conversion at the display boundary only; everything sent to the engine is SI (CLAUDE.md, conventions).

export const PA_PER_MPA = 1e6;

export function mpaToPa(mpa: number): number {
  return mpa * PA_PER_MPA;
}

export function paToMpa(pa: number): number {
  return pa / PA_PER_MPA;
}

/** Format a value for display with a fixed number of significant decimals. */
export function formatValue(value: number, decimals = 2): string {
  return value.toFixed(decimals);
}
