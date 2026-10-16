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
