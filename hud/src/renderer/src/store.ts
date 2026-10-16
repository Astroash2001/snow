import { create } from "zustand";
import type { EventsSchema, Snapshot, TranscriptRow } from "../../generated/contracts";

// The generated root type is the union of every frame on the wire.
export type WireMessage = EventsSchema;

export type Connection = "connecting" | "online" | "offline";

export interface HudState extends Required<Snapshot> {
  connection: Connection;
  partial: { turnId: string | null; text: string } | null;
}

export const initialState: HudState = {
  connection: "connecting",
  cartesia_chars_today: 0,
  conversation_id: null,
  last_seq: 0,
  mode: "awake",
  muted: false,
  presence: "sleeping",
  providers: [],
  roles: [],
  rows: [],
  stt: null,
  subsystems: [],
  voice: null,
  partial: null,
};

// One row per speaker per turn: a live Snow row is replaced in place by the final one, and a
// snapshot row for the same turn is replaced by the live final. Rows without a turn just append.
function upsertRow(rows: TranscriptRow[], row: TranscriptRow): TranscriptRow[] {
  const i =
    row.turn_id === null
      ? -1
      : rows.findIndex((r) => r.kind === row.kind && r.turn_id === row.turn_id);
  return i < 0 ? [...rows, row] : rows.map((r, j) => (j === i ? row : r));
}

function upsertBy<T>(items: T[], item: T, same: (a: T) => boolean): T[] {
  const i = items.findIndex(same);
  return i < 0 ? [...items, item] : items.map((x, j) => (j === i ? item : x));
}

const rowOf = (
  kind: TranscriptRow["kind"],
  turn: string | null | undefined,
  text: string,
  ts_ns: number,
  interrupted = false,
): TranscriptRow => ({
  kind,
  turn_id: turn ?? null,
  row_id: `${kind}:${turn ?? ts_ns}`,
  text,
  ts_ns,
  interrupted,
  system_event: null,
});

// Pure: the same state and message always give the same next state. Unknown types change nothing,
// so a newer hub never breaks an older HUD.
export function reduce(state: HudState, msg: WireMessage): HudState {
  if ("snapshot" in msg) {
    return { ...initialState, ...msg.snapshot, connection: "online" };
  }
  if (!("event" in msg)) return state;
  const e = msg.event;
  const next = typeof e.seq === "number" ? { ...state, last_seq: e.seq } : state;
  switch (e.type) {
    case "presence.state":
      return { ...next, presence: e.state, mode: e.mode };
    case "mute.changed":
      return { ...next, muted: e.muted };
    case "conversation.started":
    case "conversation.ended":
      return { ...next, rows: [], partial: null };
    case "transcript.partial":
      return { ...next, partial: { turnId: e.turn_id ?? null, text: e.text } };
    case "transcript.final":
      return {
        ...next,
        partial: null,
        rows: upsertRow(next.rows, rowOf("user", e.turn_id, e.text, e.ts_ns)),
      };
    case "reply.delta": {
      const live = next.rows.find((r) => r.kind === "snow" && r.turn_id === (e.turn_id ?? null));
      const text = (live?.text ?? "") + e.text;
      return { ...next, rows: upsertRow(next.rows, rowOf("snow", e.turn_id, text, e.ts_ns)) };
    }
    case "reply.final": {
      // An empty final is the silent all-providers-down case: drop the live row, show nothing.
      const text = e.text ?? "";
      const turn = e.turn_id ?? null;
      const rows =
        text === ""
          ? next.rows.filter((r) => !(r.kind === "snow" && r.turn_id === turn))
          : upsertRow(next.rows, rowOf("snow", e.turn_id, text, e.ts_ns));
      return { ...next, rows };
    }
    case "reply.interrupted":
      return {
        ...next,
        rows: upsertRow(next.rows, rowOf("snow", e.turn_id, e.spoken_text, e.ts_ns, true)),
      };
    case "health.subsystem":
      return { ...next, subsystems: upsertBy(next.subsystems, e, (x) => x.name === e.name) };
    case "health.provider":
      return { ...next, providers: upsertBy(next.providers, e, (x) => x.provider === e.provider) };
    case "health.role":
      return { ...next, roles: upsertBy(next.roles, e, (x) => x.role === e.role) };
    case "voice.status":
      return { ...next, voice: e };
    case "stt.status":
      return { ...next, stt: e };
    default:
      return next;
  }
}

interface Actions {
  apply: (msg: WireMessage) => void;
  setConnection: (connection: Connection) => void;
}

// Audio levels are deliberately not stored here; the orb reads them from a ref (plan 01-19).
export const useHud = create<HudState & Actions>()((set) => ({
  ...initialState,
  apply: (msg) => set((s) => reduce(s, msg)),
  setConnection: (connection) => set({ connection }),
}));
