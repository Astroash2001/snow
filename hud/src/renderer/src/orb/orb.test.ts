import { describe, expect, it } from "vitest";
import { ATTACK_MS, orbScale, RELEASE_MS, Smoother } from "./smoother";
import { buildSphere, GLYPHS, nodeCount } from "./sphere";

describe("Smoother", () => {
  it("rises with the attack time constant (63% after one 40 ms step)", () => {
    const s = new Smoother();
    s.push(0, 0);
    expect(s.push(1, ATTACK_MS)).toBeCloseTo(1 - Math.exp(-1), 5);
  });

  it("falls with the release time constant (37% left after 200 ms)", () => {
    const s = new Smoother();
    s.push(1, 0);
    s.push(1, 10_000); // settled at 1
    expect(s.push(0, 10_000 + RELEASE_MS)).toBeCloseTo(Math.exp(-1), 3);
  });

  it("attacks faster than it releases", () => {
    const up = new Smoother();
    up.push(0, 0);
    const rise = up.push(1, 50);
    const down = new Smoother();
    down.push(1, 0);
    down.push(1, 10_000);
    const fall = 1 - down.push(0, 10_050);
    expect(rise).toBeGreaterThan(fall);
  });

  it("reset() drops to silence so a barge-in does not ring out", () => {
    const s = new Smoother();
    s.push(1, 0);
    s.push(1, 500);
    expect(s.value()).toBeGreaterThan(0.9);
    s.reset();
    expect(s.value()).toBe(0);
    expect(s.push(0, 600)).toBe(0);
  });
});

describe("orbScale", () => {
  it("is 1 + 0.18 x level", () => {
    expect(orbScale(0, false)).toBe(1);
    expect(orbScale(0.5, false)).toBeCloseTo(1.09, 5);
    expect(orbScale(1, false)).toBeCloseTo(1.18, 5);
  });

  it("caps the reaction at +6% under reduced motion", () => {
    expect(orbScale(1, true)).toBeCloseTo(1.06, 5);
    expect(orbScale(0.2, true)).toBeCloseTo(1.036, 5);
  });

  it("clamps out-of-range levels", () => {
    expect(orbScale(5, false)).toBeCloseTo(1.18, 5);
    expect(orbScale(-1, false)).toBe(1);
  });
});

describe("buildSphere", () => {
  it("is deterministic for a seed and differs between seeds", () => {
    const a = buildSphere(7, 192);
    const b = buildSphere(7, 192);
    const c = buildSphere(8, 192);
    expect(a.count).toBe(b.count);
    expect(Array.from(a.x)).toEqual(Array.from(b.x));
    expect(Array.from(a.glyph)).toEqual(Array.from(b.glyph));
    expect(Array.from(a.x)).not.toEqual(Array.from(c.x));
  });

  it("has about 220 nodes at 192 px and 36 at 40 px, with edge glyphs on top", () => {
    expect(nodeCount(192)).toBe(220);
    expect(nodeCount(40)).toBe(36);
    const big = buildSphere(1, 192);
    expect(big.nodes).toBe(220);
    expect(big.count).toBeGreaterThan(big.nodes * 2);
    expect(buildSphere(1, 40).nodes).toBe(36);
  });

  it("keeps every point on the unit sphere and only valid glyph indices", () => {
    const s = buildSphere(3, 192);
    for (let i = 0; i < s.count; i++) {
      expect(Math.hypot(s.x[i], s.y[i], s.z[i])).toBeCloseTo(1, 4);
      expect(s.glyph[i]).toBeLessThan(GLYPHS.length);
    }
    expect(s.isNode.slice(0, s.nodes).every((v) => v === 1)).toBe(true);
    expect(s.isNode.slice(s.nodes).every((v) => v === 0)).toBe(true);
  });

  it("mixes symbols, digits and code fragments", () => {
    for (const g of ["for", "{}", "=>", "0x", "json", "1", "0"]) expect(GLYPHS).toContain(g);
  });

  it("flicker changes glyphs but never positions", () => {
    const s = buildSphere(5, 192);
    const before = Array.from(s.glyph);
    const x = Array.from(s.x);
    s.flicker(200);
    expect(Array.from(s.glyph)).not.toEqual(before);
    expect(Array.from(s.x)).toEqual(x);
  });
});
