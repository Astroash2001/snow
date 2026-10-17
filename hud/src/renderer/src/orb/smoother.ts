export const ATTACK_MS = 40;
export const RELEASE_MS = 200;

// Exponential smoother with separate attack (rising) and release (falling) time constants, so the
// orb jumps up with the voice and eases back down. Time is passed in, which keeps it testable.
export class Smoother {
  private v = 0;
  private last: number | null = null;

  /** Moves toward `target` for the time elapsed since the last push and returns the new value. */
  push(target: number, now: number): number {
    if (this.last !== null) {
      const dt = Math.max(0, now - this.last);
      const tau = target > this.v ? ATTACK_MS : RELEASE_MS;
      this.v += (target - this.v) * (1 - Math.exp(-dt / tau));
    }
    this.last = now;
    return this.v;
  }

  value(): number {
    return this.v;
  }

  /** Back to silence at once (barge-in: the orb must not ring out). */
  reset(): void {
    this.v = 0;
    this.last = null;
  }
}

// UI-SPEC level mapping: 1 + 0.18 x level; reduced motion caps the reaction at +6%.
export function orbScale(level: number, reducedMotion: boolean): number {
  const gain = 0.18 * Math.min(1, Math.max(0, level));
  return 1 + (reducedMotion ? Math.min(gain, 0.06) : gain);
}
