import { useEffect, useRef, useState } from "react";
import { copy } from "../copy";
import { useHud } from "../store";
import { sendCommand } from "../ws";

// Asks the hub to flip the microphone. It reads the confirmed state, so a click never changes what
// the UI shows: the label, banner and orb change only when the hub's mute.changed arrives.
export function toggleMute(): void {
  const { connection, muted } = useHud.getState();
  if (connection !== "online") return;
  sendCommand({ type: "cmd.mute.set", muted: !muted, by: "hud" });
}

const PRESSED_MS = 120;

// The one primary button. Accent text and border while the mic is live; alert hue while muted.
export function MuteButton({ testId = "mute-button" }: { testId?: string }) {
  const muted = useHud((s) => s.muted);
  const online = useHud((s) => s.connection === "online");
  const [pressed, setPressed] = useState(false);
  const timer = useRef<ReturnType<typeof setTimeout>>(undefined);
  useEffect(() => () => clearTimeout(timer.current), []);

  const onClick = () => {
    setPressed(true);
    clearTimeout(timer.current);
    timer.current = setTimeout(() => setPressed(false), PRESSED_MS);
    toggleMute();
  };

  return (
    <button
      type="button"
      data-testid={testId}
      data-pressed={pressed}
      disabled={!online}
      onClick={onClick}
      className={`h-10 cursor-pointer rounded-(--snow-radius-button) border bg-transparent px-4 text-sm font-semibold transition-colors duration-(--snow-duration-fast) enabled:data-[pressed=true]:bg-(--snow-border) disabled:cursor-not-allowed disabled:opacity-50 ${
        muted
          ? "border-(--snow-alert) text-(--snow-alert)"
          : "border-(--snow-accent) text-(--snow-accent)"
      }`}
    >
      {muted ? copy.unmute : copy.mute}
    </button>
  );
}
