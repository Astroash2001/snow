import { mkdtempSync, rmSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { afterEach, describe, expect, it } from "vitest";
import {
  clampToWorkArea,
  type DisplayInfo,
  defaultPosition,
  loadPosition,
  MINI_H,
  MINI_W,
  onLeftHalf,
  savePosition,
} from "./position";

const d1: DisplayInfo = { id: 1, workArea: { x: 0, y: 0, width: 1920, height: 1040 } };
// A second monitor to the right, a different size (mixed DPI shows up as different DIP sizes).
const d2: DisplayInfo = { id: 2, workArea: { x: 1920, y: 0, width: 1280, height: 680 } };

describe("clampToWorkArea", () => {
  it("falls back to the top-right of the primary display when the saved display is gone", () => {
    const pos = clampToWorkArea({ x: 2500, y: 100, displayId: 2 }, [d1], d1);
    expect(pos).toEqual({ x: 1920 - MINI_W - 16, y: 16 });
  });

  it("uses the default when nothing was saved", () => {
    expect(clampToWorkArea(null, [d1, d2], d1)).toEqual(defaultPosition(d1));
  });

  it("keeps a position that is already fully inside its display", () => {
    expect(clampToWorkArea({ x: 2000, y: 300, displayId: 2 }, [d1, d2], d1)).toEqual({
      x: 2000,
      y: 300,
    });
  });

  it("pulls a position that is partly off-screen fully inside that display", () => {
    const right = clampToWorkArea({ x: 1800, y: 5, displayId: 1 }, [d1], d1);
    expect(right).toEqual({ x: 1920 - MINI_W, y: 5 });
    const below = clampToWorkArea({ x: 10, y: 1000, displayId: 1 }, [d1], d1);
    expect(below).toEqual({ x: 10, y: 1040 - MINI_H });
    const left = clampToWorkArea({ x: -100, y: -20, displayId: 1 }, [d1], d1);
    expect(left).toEqual({ x: 0, y: 0 });
  });

  it("clamps into the work area of the smaller display it was saved on", () => {
    const pos = clampToWorkArea({ x: 3100, y: 660, displayId: 2 }, [d1, d2], d1);
    expect(pos).toEqual({ x: 3200 - MINI_W, y: 680 - MINI_H });
  });

  it("respects a work area that does not start at the origin (taskbar on the top or left)", () => {
    const shifted: DisplayInfo = { id: 3, workArea: { x: 48, y: 40, width: 1000, height: 600 } };
    expect(clampToWorkArea({ x: 0, y: 0, displayId: 3 }, [shifted], shifted)).toEqual({
      x: 48,
      y: 40,
    });
  });
});

describe("onLeftHalf", () => {
  it("is true when the window center is left of the display center", () => {
    expect(onLeftHalf({ x: 100, y: 0 }, d1)).toBe(true);
    expect(onLeftHalf({ x: 1920 - MINI_W - 16, y: 0 }, d1)).toBe(false);
  });

  it("measures against the display the window is on", () => {
    expect(onLeftHalf({ x: 1920, y: 0 }, d2)).toBe(true);
    expect(onLeftHalf({ x: 2900, y: 0 }, d2)).toBe(false);
  });
});

describe("persisted position", () => {
  let dir = "";
  afterEach(() => rmSync(dir, { recursive: true, force: true }));

  it("round-trips, and a missing or corrupt file is no position", () => {
    dir = mkdtempSync(join(tmpdir(), "snow-pos-"));
    const file = join(dir, "mini-position.json");
    expect(loadPosition(file)).toBeNull();
    savePosition(file, { x: 12, y: 34, displayId: 5 });
    expect(loadPosition(file)).toEqual({ x: 12, y: 34, displayId: 5 });
    writeFileSync(file, "{not json");
    expect(loadPosition(file)).toBeNull();
    writeFileSync(file, JSON.stringify({ x: "1", y: 2, displayId: 3 }));
    expect(loadPosition(file)).toBeNull();
  });
});
