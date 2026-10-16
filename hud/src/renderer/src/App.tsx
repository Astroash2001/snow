import { useEffect, useRef, useState } from "react";
import { type Connection, type HudState, useHud } from "./store";

const WORDS: Record<HudState["presence"], string> = {
  sleeping: "Standing by",
  listening: "Listening",
  thinking: "Thinking",
  speaking: "Speaking",
  muted: "Muted",
};

// Text for the visually hidden role="status" region: "Reconnected" after a lost connection returns.
// Connection lost is announced by the banner's role="alert".
function useReconnectedAnnouncement(connection: Connection): string {
  const [text, setText] = useState("");
  const wasLost = useRef(false);
  useEffect(() => {
    if (connection === "offline") {
      wasLost.current = true;
      setText("");
    } else if (connection === "online" && wasLost.current) {
      wasLost.current = false;
      setText("Reconnected");
    }
  }, [connection]);
  return text;
}

// Plan 01-21 replaces the row list with the full TranscriptView and moves the banner into the shared
// Banner component; text is always a React text node.
export function App() {
  const presence = useHud((s) => s.presence);
  const connection = useHud((s) => s.connection);
  const rows = useHud((s) => s.rows);
  const partial = useHud((s) => s.partial);
  const announcement = useReconnectedAnnouncement(connection);
  const word = connection === "offline" ? "Reconnecting" : WORDS[presence];
  return (
    <>
      {connection === "offline" && (
        <div
          role="alert"
          data-testid="connection-banner"
          className="m-4 mb-0 rounded-(--snow-radius-card) border border-(--snow-alert) bg-(--snow-surface) p-4"
        >
          <h2 className="text-xl leading-[1.2] font-semibold text-(--snow-text)">
            Cannot reach Snow's core
          </h2>
          <p className="mt-1 text-sm text-(--snow-text-2)">
            Reconnecting automatically. Mute is unavailable until the connection returns.
          </p>
        </div>
      )}
      <div role="status" data-testid="status-region" className="sr-only">
        {announcement}
      </div>
      <main className="p-4">
        <h1 className="text-[28px] leading-[1.2] font-semibold" data-testid="state-word">
          {word}
        </h1>
        <ul className="mt-4 space-y-2">
          {rows.map((row) => (
            <li key={row.row_id} data-testid={`row-${row.kind}`}>
              <span className="mr-2 text-xs font-semibold text-(--snow-text-3)">
                {row.kind === "user" ? "You" : row.kind === "snow" ? "Snow" : "System"}
              </span>
              <span>{row.text}</span>
            </li>
          ))}
          {partial && (
            <li className="text-(--snow-text-2)" data-testid="row-partial">
              <span className="mr-2 text-xs font-semibold text-(--snow-text-3)">You</span>
              <span>{partial.text}</span>
            </li>
          )}
        </ul>
      </main>
    </>
  );
}
