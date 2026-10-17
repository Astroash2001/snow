import { create } from "zustand";
import type { EventsSchema, Snapshot, TranscriptRow } from "../../generated/contracts";

// The generated root type is the union of every frame on the wire.
export type WireMessage = EventsSchema;

export type Connection = "connecting" | "online" | "offline";

export interface HudState extends Required<Snapshot> {
  connection: Connection;
  partial: { turnId: string | null; text: string } | null;
  /** The conversation ended; the rows stay readable until TranscriptView calls clearTranscript. */
  ended: boolean;
  /** row_id of the Snow row still receiving reply deltas, so screen readers skip half-written text. */
  streaming: string | null;
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
  ended: false,
  streaming: null,
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

// A system row carries the same key=value facts the hub writes into snapshot rows; copy.ts turns
// them into the sentence, so live and snapshot rows render the same.
const systemRow = (
  e: { type?: string; seq?: number | null; ts_ns: number; turn_id?: string | null },
  facts: string,
): TranscriptRow => ({
  kind: "system",
  turn_id: e.turn_id ?? null,
  row_id: `system:${e.seq ?? e.ts_ns}`,
  text: facts,
  ts_ns: e.ts_ns,
  interrupted: false,
  system_event: e.type ?? null,
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
      // Leaving "listening" with words still unfinalized means the turn had no speech to keep.
      return {
        ...next,
        presence: e.state,
        mode: e.mode,
        partial: e.state === "listening" ? next.partial : null,
      };
    case "mute.changed":
      return { ...next, muted: e.muted };
    case "conversation.started":
      return { ...next, rows: [], partial: null, ended: false, streaming: null };
    case "conversation.ended":
      // The rows stay readable; TranscriptView clears them after its 2 s hold and 300 ms fade.
      return { ...next, partial: null, ended: true };
    case "transcript.partial":
      return { ...next, partial: { turnId: e.turn_id ?? null, text: e.text } };
    case "turn.cancelled":
      return { ...next, partial: null };
    case "transcript.final":
      // A final with no words is a turn with no speech: no row, no leftover partial.
      return {
        ...next,
        partial: null,
        rows:
          e.text.trim() === ""
            ? next.rows
            : upsertRow(next.rows, rowOf("user", e.turn_id, e.text, e.ts_ns)),
      };
    case "reply.delta": {
      const live = next.rows.find((r) => r.kind === "snow" && r.turn_id === (e.turn_id ?? null));
      const text = (live?.text ?? "") + e.text;
      const row = rowOf("snow", e.turn_id, text, live?.ts_ns ?? e.ts_ns);
      return { ...next, streaming: row.row_id, rows: upsertRow(next.rows, row) };
    }
    case "reply.final": {
      // An empty final is the silent all-providers-down case: drop the live row, show nothing.
      const text = e.text ?? "";
      const turn = e.turn_id ?? null;
      const rows =
        text === ""
          ? next.rows.filter((r) => !(r.kind === "snow" && r.turn_id === turn))
          : upsertRow(next.rows, rowOf("snow", e.turn_id, text, e.ts_ns));
      return { ...next, streaming: null, rows };
    }
    case "reply.interrupted": {
      // Keep what was heard; if nothing was, there is no row to dim.
      const turn = e.turn_id ?? null;
      const rows =
        e.spoken_text === ""
          ? next.rows.filter((r) => !(r.kind === "snow" && r.turn_id === turn))
          : upsertRow(next.rows, rowOf("snow", e.turn_id, e.spoken_text, e.ts_ns, true));
      return { ...next, streaming: null, rows };
    }
    case "llm.switch":
      return {
        ...next,
        rows: [
          ...next.rows,
          systemRow(
            e,
            `role=${e.role} from=${e.from_provider}/${e.from_model}` +
              ` to=${e.to_provider}/${e.to_model} reason=${e.switch_reason}`,
          ),
        ],
      };
    case "llm.blocked_privacy":
      return {
        ...next,
        rows: [...next.rows, systemRow(e, `role=${e.role} data_class=${e.data_class}`)],
      };
    case "llm.exhausted":
      return { ...next, rows: [...next.rows, systemRow(e, `role=${e.role}`)] };
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
  /** Empties the transcript after the end-of-conversation hold and fade (timers live in the view). */
  clearTranscript: () => void;
}

// Audio levels are deliberately not stored here; the orb reads them from a ref (plan 01-19).
export const useHud = create<HudState & Actions>()((set) => ({
  ...initialState,
  apply: (msg) => set((s) => reduce(s, msg)),
  setConnection: (connection) => set({ connection }),
  clearTranscript: () => set({ rows: [], partial: null, ended: false, streaming: null }),
}));
