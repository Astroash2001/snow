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
  it("replays the golden conversation to a sleeping state with the rows still readable", () => {
    const end = [snapshot, ...lines].reduce(reduce, initialState);
    expect(end.presence).toBe("sleeping");
    expect(end.connection).toBe("online");
    // conversation.ended keeps the rows for the view to fade out; the view then clears them.
    expect(end.ended).toBe(true);
    expect(end.rows.length).toBeGreaterThan(0);
    expect(end.rows.some((r) => r.kind === "system" && r.system_event === "llm.switch")).toBe(true);
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

  it("conversation.ended keeps the rows and drops the partial until the view clears them", () => {
    const s = reduce(
      run(ev("transcript.final", { text: "hi" }), ev("transcript.partial", { text: "x" })),
      ev("conversation.ended"),
    );
    expect(s.ended).toBe(true);
    expect(s.partial).toBeNull();
    expect(s.rows).toHaveLength(1);
    expect(reduce(s, ev("conversation.started")).ended).toBe(false);
  });

  it("a turn with no speech leaves no partial and no row", () => {
    const partial = run(ev("transcript.partial", { text: "um" }));
    const blank = reduce(partial, ev("transcript.final", { text: "  " }));
    expect(blank.rows).toEqual([]);
    expect(blank.partial).toBeNull();
    const thinking = reduce(partial, ev("presence.state", { state: "thinking", mode: "awake" }));
    expect(thinking.partial).toBeNull();
    expect(reduce(partial, ev("turn.cancelled")).partial).toBeNull();
    const stillListening = reduce(
      partial,
      ev("presence.state", { state: "listening", mode: "awake" }),
    );
    expect(stillListening.partial).toEqual(partial.partial);
  });

  it("marks the Snow row as streaming until the final, and an empty interrupt leaves no row", () => {
    const live = run(ev("reply.delta", { text: "Hel" }), ev("reply.delta", { text: "lo" }));
    expect(live.streaming).toBe("snow:t1");
    expect(reduce(live, ev("reply.final", { text: "Hello" })).streaming).toBeNull();
    const heard = reduce(live, ev("reply.interrupted", { spoken_text: "Hel" }));
    expect(heard.rows.map((r) => [r.text, r.interrupted])).toEqual([["Hel", true]]);
    expect(reduce(live, ev("reply.interrupted", { spoken_text: "" })).rows).toEqual([]);
  });

  it("llm events become system rows in the hub's key=value shape", () => {
    const s = run(
      ev("llm.switch", {
        role: "brain",
        from_provider: "a",
        from_model: "m1",
        to_provider: "b",
        to_model: "m2",
        switch_reason: "rate_limit",
      }),
      ev("llm.blocked_privacy", { role: "fast", data_class: "private" }),
      ev("llm.exhausted", { role: "brain" }),
    );
    expect(s.rows.map((r) => [r.kind, r.system_event, r.text])).toEqual([
      ["system", "llm.switch", "role=brain from=a/m1 to=b/m2 reason=rate_limit"],
      ["system", "llm.blocked_privacy", "role=fast data_class=private"],
      ["system", "llm.exhausted", "role=brain"],
    ]);
  });

  it("returns the same state object for an unknown event type", () => {
    const s = run(ev("transcript.final", { text: "hi" }));
    expect(reduce(s, ev("future.thing"))).toBe(s);
  });
});
