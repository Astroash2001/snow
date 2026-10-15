import Ajv2020 from "ajv/dist/2020";
import { describe, expect, it } from "vitest";
import schema from "../../../../contracts/events.schema.json";
import conversationRaw from "../../../../contracts/samples/conversation-12.jsonl?raw";
import samples from "../../../../contracts/samples/events.json";
import type { EventsSchema } from "../../generated/contracts";

// The generated root type is the union of every frame on the wire.
type WireMessage = EventsSchema;

// strict: false because Pydantic emits keywords (discriminator, title, default) ajv strict mode rejects.
const validate = new Ajv2020({ strict: false, allErrors: true }).compile(schema);

const check = (label: string, value: unknown) => {
  const ok = validate(value);
  expect(ok, `${label}: ${JSON.stringify(validate.errors)}`).toBe(true);
};

describe("golden samples validate against contracts/events.schema.json", () => {
  const entries = Object.entries(samples as Record<string, unknown>);

  it("has samples", () => {
    expect(entries.length).toBeGreaterThan(30);
  });

  it.each(entries)("events.json: %s", (name, sample) => {
    check(name, sample);
  });

  const lines = conversationRaw.split("\n").filter((l) => l.trim() !== "");

  it("conversation-12.jsonl has lines", () => {
    expect(lines.length).toBeGreaterThan(100);
  });

  it.each(lines.map((l, i) => [i + 1, l] as const))("conversation-12.jsonl line %i", (n, line) => {
    check(`line ${n}`, JSON.parse(line));
  });

  it("rejects an unknown frame kind", () => {
    expect(validate({ kind: "nope" })).toBe(false);
  });

  it("a sample is assignable to the generated WireMessage type", () => {
    const msg: WireMessage = (samples as Record<string, WireMessage>)["transcript.final"];
    expect(msg.kind).toBe("event");
  });
});
