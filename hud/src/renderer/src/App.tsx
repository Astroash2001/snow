import { MicOff, Moon, XCircle } from "lucide-react";
import { useEffect, useRef, useState } from "react";
import { Banner } from "./components/Banner";
import { HealthPanel } from "./components/HealthPanel";
import { MuteButton, toggleMute } from "./components/MuteButton";
import { Presence, STATE_WORDS } from "./components/Presence";
import { TranscriptView } from "./components/TranscriptView";
import { VoiceCard } from "./components/VoiceCard";
import { copy } from "./copy";
import { installSnowTestHook } from "./orb/renderer";
import { type Connection, selectAlert, useHud } from "./store";
import { sendCommand } from "./ws";

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

// False while the shell has the dashboard hidden. Showing it again asks for a fresh snapshot, so a
// conversation that went on meanwhile is fully there when the window comes back.
function useDashboardVisible(): boolean {
  const [visible, setVisible] = useState(true);
  useEffect(
    () =>
      window.snow.chrome.onVisibility((v) => {
        setVisible(v);
        if (v) sendCommand({ type: "cmd.snapshot" });
      }),
    [],
  );
  return visible;
}

// The dashboard: presence card on the left, the transcript on the right. Text is always a React
// text node.
export function App() {
  const presence = useHud((s) => s.presence);
  const mode = useHud((s) => s.mode);
  const muted = useHud((s) => s.muted);
  const connection = useHud((s) => s.connection);
  const alert = useHud(selectAlert);
  const announcement = useAnnouncement(connection);
  const visible = useDashboardVisible();
  const word = connection === "offline" ? STATE_WORDS.offline : STATE_WORDS[presence];
  // Before the first snapshot and while the socket is down the orb shows its offline style.
  const orbState = connection === "online" ? presence : "offline";
  // Hidden: nothing is rendered, so the orb loop stops and the transcript and health trees unmount.
  if (!visible) return null;
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
        {/* DOM order is the Tab order (Mute, orb, role disclosures, Jump to latest); the
            flex "order" classes put each block where the layout wants it. */}
        <div className="flex min-h-0 w-80 shrink-0 flex-col gap-4 overflow-y-auto">
          <section
            aria-label="Presence"
            className="flex h-fit shrink-0 flex-col items-center gap-2 rounded-(--snow-radius-card) border border-(--snow-border) bg-(--snow-surface) p-4"
          >
            <div className="order-4">
              <MuteButton />
            </div>
            <div className="order-1">
              <Presence state={orbState} size={192} alert={alert} onClick={toggleMute} />
            </div>
            <h1
              className="order-2 text-(length:--snow-size-display) leading-(--snow-leading-heading) font-semibold"
              data-testid="state-word"
            >
              {word}
            </h1>
            {connection === "online" && mode === "soft_sleep" && (
              <span
                data-testid="mode-chip"
                className="order-3 flex items-center gap-1 rounded-(--snow-radius-pill) border border-(--snow-border) px-2 text-xs text-(--snow-text-2)"
              >
                <Moon aria-hidden="true" className="size-3" />
                {copy.asleepChip}
              </span>
            )}
          </section>
          <VoiceCard />
        </div>
        <div className="flex min-h-0 min-w-0 flex-1 flex-col gap-4">
          <div className="order-2 shrink-0">
            <HealthPanel />
          </div>
          <div className="order-1 flex min-h-60 flex-1 flex-col">
            <TranscriptView />
          </div>
        </div>
      </main>
    </div>
  );
}
