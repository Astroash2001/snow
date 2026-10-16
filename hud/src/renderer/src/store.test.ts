import { describe, expect, it } from "vitest";
import conversationRaw from "../../../../contracts/samples/conversation-12.jsonl?raw";
import samples from "../../../../contracts/samples/events.json";
import { initialState, reduce, type WireMessage } from "./store";

const snapshot = samples.snapshot as WireMessage;
const lines = conversationRaw
  .split("\n")
  .filter((l) => l.trim() !== "")
  .map((l) => JSON.parse(l) as WireMessage);

describe("reduce", () => {
  it("replays the golden conversation to a cleared, sleeping state", () => {
    const end = [snapshot, ...lines].reduce(reduce, initialState);
    expect(end.presence).toBe("sleeping");
    expect(end.rows).toEqual([]);
    expect(end.connection).toBe("online");
  });

  it("builds a You row and a Snow row for a turn, replacing the live Snow text", () => {
    const upTo = (type: string) => lines.findIndex((m) => "event" in m && m.event.type === type);
    const s = lines
      .slice(0, upTo("reply.final") + 1)
      .reduce(reduce, reduce(initialState, snapshot));
    expect(s.rows.map((r) => [r.kind, r.text])).toEqual([
      ["user", "good morning snow"],
      ["snow", "Good morning. Ready when you are."],
    ]);
  });

  it("ignores unknown event types and non-event frames", () => {
    const unknown = { kind: "event", event: { type: "future.thing", ts_ns: 1 } } as never;
    expect(reduce(initialState, unknown)).toBe(initialState);
    expect(reduce(initialState, { kind: "hello" } as never)).toBe(initialState);
  });
});

// Minimal hand-built frames: the reducer reads only type, turn_id, text and ts_ns.
const ev = (type: string, fields: Record<string, unknown> = {}) =>
  ({
    kind: "event",
    event: { type, ts_ns: 1, turn_id: "t1", ...fields },
  }) as unknown as WireMessage;
const run = (...msgs: WireMessage[]) => msgs.reduce(reduce, initialState);

describe("reduce, turn building", () => {
  it("a final transcript adds a You row and clears the partial", () => {
    const mid = run(ev("transcript.partial", { text: "hel" }));
    expect(mid.partial).toEqual({ turnId: "t1", text: "hel" });
    const s = reduce(mid, ev("transcript.final", { text: "hello snow" }));
    expect(s.partial).toBeNull();
    expect(s.rows.map((r) => [r.kind, r.text])).toEqual([["user", "hello snow"]]);
  });

  it("a final after a snapshot appends a You row to the snapshot's rows", () => {
    const s = reduce(
      reduce(initialState, snapshot),
      ev("transcript.final", { text: "next", turn_id: "t9" }),
    );
    expect(s.connection).toBe("online");
    expect(s.rows.at(-1)).toMatchObject({ kind: "user", text: "next" });
    expect(s.rows.length).toBeGreaterThan(1);
  });

  it("reply deltas build one Snow row and the final replaces its text", () => {
    const live = run(...["Good ", "morning", "!"].map((text) => ev("reply.delta", { text })));
    expect(live.rows.map((r) => [r.kind, r.text])).toEqual([["snow", "Good morning!"]]);
    const done = reduce(live, ev("reply.final", { text: "Good morning. Ready." }));
    expect(done.rows.map((r) => [r.kind, r.text])).toEqual([["snow", "Good morning. Ready."]]);
  });

  it("conversation.started clears the rows and the partial", () => {
    const s = run(ev("transcript.final", { text: "hi" }), ev("transcript.partial", { text: "x" }));
    expect(s.rows).toHaveLength(1);
    const cleared = reduce(s, ev("conversation.started"));
    expect(cleared.rows).toEqual([]);
    expect(cleared.partial).toBeNull();
  });

  it("returns the same state object for an unknown event type", () => {
    const s = run(ev("transcript.final", { text: "hi" }));
    expect(reduce(s, ev("future.thing"))).toBe(s);
  });
});
