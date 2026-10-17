import { describe, expect, it } from "vitest";
import { copy, systemRowText } from "./copy";

describe("systemRowText", () => {
  const facts = "role=brain from=a/m1 to=groq/m2 reason=";
  it("fills the provider-switched template and maps wire reasons to the contract words", () => {
    const label = (id: string) => (id === "groq" ? "Groq" : id);
    expect(systemRowText("llm.switch", `${facts}rate_limit`, label)).toBe(
      "Switched brain model to Groq (rate limit).",
    );
    for (const [wire, words] of [
      ["out_of_quota", "out of quota"],
      ["timeout", "timeout"],
      ["unreachable", "unreachable"],
      ["bad_key", "service error"],
      ["config_error", "service error"],
    ]) {
      expect(systemRowText("llm.switch", `${facts}${wire}`)).toContain(`(${words})`);
    }
  });

  it("uses the documented sentences for exhausted chains and privacy holds", () => {
    expect(systemRowText("llm.exhausted", "role=brain")).toBe(copy.noModelReachable);
    expect(systemRowText("llm.blocked_privacy", "role=fast data_class=private")).toBe(
      copy.privacyBlock,
    );
  });

  it("falls back to the stored text for rows it does not know", () => {
    expect(systemRowText(null, "something happened")).toBe("something happened");
    expect(systemRowText("llm.switch", "garbled")).toBe("garbled");
  });
});
