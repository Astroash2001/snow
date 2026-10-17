import { useEffect, useRef } from "react";
import { TEST_MODE } from "../levels";
import type { OrbState } from "../orb/atlas";
import { OrbRenderer } from "../orb/renderer";
import { useHud } from "../store";

export const STATE_WORDS: Record<OrbState, string> = {
  sleeping: "Standing by",
  listening: "Listening",
  thinking: "Thinking",
  speaking: "Speaking",
  muted: "Muted",
  offline: "Reconnecting",
};

const SEED = 7;

interface PresenceProps {
  state: OrbState;
  size: number;
  /** The 8 px alert dot: a subsystem is Down or Restarting, or a language-model role is Failing. */
  alert: boolean;
  /** Frame-rate cap while awake; the mini window passes 30. */
  fpsCap?: number;
  onClick?: () => void;
}

// Snow's face: the ASCII network orb on a Canvas 2D glyph atlas. Levels come from a ref (levels.ts),
// never from React state, so the 30 Hz audio stream causes no re-render.
export function Presence({ state, size, alert, fpsCap = 60, onClick }: PresenceProps) {
  const canvas = useRef<HTMLCanvasElement>(null);
  const orb = useRef<OrbRenderer | null>(null);
  const latest = useRef({ state, alert });
  latest.current = { state, alert };

  useEffect(() => {
    if (!canvas.current) return;
    const r = new OrbRenderer(canvas.current, { size, fpsCap, seed: SEED, ...latest.current });
    orb.current = r;
    r.start();
    return () => {
      r.stop();
      orb.current = null;
    };
  }, [size, fpsCap]);

  useEffect(() => {
    // last_seq is read only for the perf marks, and only in test runs.
    orb.current?.setState(state, TEST_MODE ? useHud.getState().last_seq : undefined);
  }, [state]);

  useEffect(() => {
    orb.current?.setAlert(alert);
  }, [alert]);

  return (
    <button
      type="button"
      aria-label={`Snow, ${STATE_WORDS[state]}`}
      onClick={onClick}
      className="block cursor-pointer rounded-full border-0 bg-transparent p-0"
    >
      <canvas ref={canvas} className="block" />
    </button>
  );
}
