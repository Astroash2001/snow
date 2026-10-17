import { MicOff, Moon, XCircle } from "lucide-react";
import { useEffect, useRef, useState } from "react";
import { Banner } from "./components/Banner";
import { MuteButton, toggleMute } from "./components/MuteButton";
import { Presence, STATE_WORDS } from "./components/Presence";
import { TranscriptView } from "./components/TranscriptView";
import { copy } from "./copy";
import { installSnowTestHook } from "./orb/renderer";
import { type Connection, useHud } from "./store";

installSnowTestHook();

// Text for the visually hidden role="status" region. It says only: muted, unmuted, a subsystem
// going Down, connection lost, connection restored. The first snapshot after launch announces
// nothing, and a change that arrives with a reconnect reads as "Reconnected".
function useAnnouncement(connection: Connection): string {
  const muted = useHud((s) => s.muted);
  const downKey = useHud((s) =>
    s.subsystems
      .filter((x) => x.status === "down")
      .map((x) => x.label)
      .join("|"),
  );
  const [text, setText] = useState("");
  const prev = useRef<{ connection: Connection; muted: boolean; down: string[] } | null>(null);
  useEffect(() => {
    const down = downKey === "" ? [] : downKey.split("|");
    const before = prev.current;
    prev.current = { connection, muted, down };
    if (!before) return;
    if (connection !== before.connection) {
      if (connection === "offline") setText(copy.announce.connectionLost);
      else if (connection === "online" && before.connection === "offline") {
        setText(copy.announce.reconnected);
      }
    } else if (muted !== before.muted) {
      setText(muted ? copy.announce.muted : copy.announce.unmuted);
    } else {
      const added = down.filter((n) => !before.down.includes(n));
      if (added.length > 0) setText(copy.announce.subsystemDown(added));
    }
  }, [connection, muted, downKey]);
  return text;
}

// The dashboard: presence card on the left, the transcript on the right. Text is always a React
// text node.
export function App() {
  const presence = useHud((s) => s.presence);
  const mode = useHud((s) => s.mode);
  const muted = useHud((s) => s.muted);
  const connection = useHud((s) => s.connection);
  const subsystems = useHud((s) => s.subsystems);
  const roles = useHud((s) => s.roles);
  const announcement = useAnnouncement(connection);
  const word = connection === "offline" ? STATE_WORDS.offline : STATE_WORDS[presence];
  // Before the first snapshot and while the socket is down the orb shows its offline style.
  const orbState = connection === "online" ? presence : "offline";
  // Also covers the silent all-providers-down case (D-41): Snow cannot reply, so the orb says so.
  const alert =
    subsystems.some((s) => s.status === "down" || s.status === "restarting") ||
    roles.some((r) => r.status === "failing");
  return (
    <div className="flex h-screen flex-col">
      {connection === "offline" && (
        <Banner icon={XCircle} title={copy.connectionBanner.heading} testId="connection-banner">
          {copy.connectionBanner.body}
        </Banner>
      )}
      {/* The mute state is only claimed while the core confirms it; offline, the connection banner speaks. */}
      {connection === "online" && muted && (
        <Banner
          icon={MicOff}
          testId="mute-banner"
          action={<MuteButton testId="banner-unmute-button" />}
        >
          {copy.muteBanner}
        </Banner>
      )}
      <div role="status" data-testid="status-region" className="sr-only">
        {announcement}
      </div>
      <main className="flex min-h-0 flex-1 gap-4 p-4">
        <section
          aria-label="Presence"
          className="flex h-fit w-80 shrink-0 flex-col items-center gap-2 rounded-(--snow-radius-card) border border-(--snow-border) bg-(--snow-surface) p-4"
        >
          <Presence state={orbState} size={192} alert={alert} onClick={toggleMute} />
          <h1
            className="text-(length:--snow-size-display) leading-(--snow-leading-heading) font-semibold"
            data-testid="state-word"
          >
            {word}
          </h1>
          {connection === "online" && mode === "soft_sleep" && (
            <span
              data-testid="mode-chip"
              className="flex items-center gap-1 rounded-(--snow-radius-pill) border border-(--snow-border) px-2 text-xs text-(--snow-text-2)"
            >
              <Moon aria-hidden="true" className="size-3" />
              {copy.asleepChip}
            </span>
          )}
          <MuteButton />
        </section>
        <TranscriptView />
      </main>
    </div>
  );
}
