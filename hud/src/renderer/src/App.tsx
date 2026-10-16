import { type HudState, useHud } from "./store";

const WORDS: Record<HudState["presence"], string> = {
  sleeping: "Standing by",
  listening: "Listening",
  thinking: "Thinking",
  speaking: "Speaking",
  muted: "Muted",
};

// Plan 01-21 replaces the row list with the full TranscriptView; text is always a React text node.
export function App() {
  const presence = useHud((s) => s.presence);
  const connection = useHud((s) => s.connection);
  const rows = useHud((s) => s.rows);
  const partial = useHud((s) => s.partial);
  const word = connection === "offline" ? "Reconnecting" : WORDS[presence];
  return (
    <main className="p-4">
      <h1 className="text-[28px] font-semibold leading-[1.2]" data-testid="state-word">
        {word}
      </h1>
      <ul className="mt-4 space-y-2">
        {rows.map((row) => (
          <li key={row.row_id} data-testid={`row-${row.kind}`}>
            <span className="mr-2 text-xs font-semibold text-[#8089a0]">
              {row.kind === "user" ? "You" : row.kind === "snow" ? "Snow" : "System"}
            </span>
            <span>{row.text}</span>
          </li>
        ))}
        {partial && (
          <li className="text-[#a8b1c5]" data-testid="row-partial">
            <span className="mr-2 text-xs font-semibold text-[#8089a0]">You</span>
            <span>{partial.text}</span>
          </li>
        )}
      </ul>
    </main>
  );
}
