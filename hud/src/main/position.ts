import { readFileSync, writeFileSync } from "node:fs";

export const MINI_W = 320;
export const MINI_H = 56;
export const MINI_MARGIN = 16;

export interface Rect {
  x: number;
  y: number;
  width: number;
  height: number;
}
export interface DisplayInfo {
  id: number;
  workArea: Rect;
}
export interface Point {
  x: number;
  y: number;
}
/** Where the mini window was left: DIP coordinates plus the display it was on. */
export interface SavedPosition extends Point {
  displayId: number;
}

/** Top-right of a display's work area, 16 px from the top and right edges. */
export function defaultPosition(display: DisplayInfo): Point {
  const w = display.workArea;
  return { x: w.x + w.width - MINI_W - MINI_MARGIN, y: w.y + MINI_MARGIN };
}

const clamp = (v: number, lo: number, hi: number) => Math.min(Math.max(v, lo), Math.max(lo, hi));

/**
 * Where the mini window goes at startup and after a display change. A saved position whose display
 * is gone (or no saved position) gives the default; otherwise the window is pulled fully inside
 * that display's work area.
 */
export function clampToWorkArea(
  saved: SavedPosition | null,
  displays: DisplayInfo[],
  primary: DisplayInfo,
): Point {
  const display = saved && displays.find((d) => d.id === saved.displayId);
  if (!saved || !display) return defaultPosition(primary);
  const w = display.workArea;
  return {
    x: clamp(saved.x, w.x, w.x + w.width - MINI_W),
    y: clamp(saved.y, w.y, w.y + w.height - MINI_H),
  };
}

/** True when the window's center is on the left half of the display (the row then mirrors). */
export function onLeftHalf(pos: Point, display: DisplayInfo): boolean {
  const w = display.workArea;
  return pos.x + MINI_W / 2 < w.x + w.width / 2;
}

const finite = (n: unknown): n is number => typeof n === "number" && Number.isFinite(n);

/** Reads the persisted position; a missing, corrupt or malformed file is no position. */
export function loadPosition(file: string): SavedPosition | null {
  try {
    const p = JSON.parse(readFileSync(file, "utf8")) as Partial<SavedPosition>;
    return finite(p.x) && finite(p.y) && finite(p.displayId)
      ? { x: p.x, y: p.y, displayId: p.displayId }
      : null;
  } catch {
    return null;
  }
}

export function savePosition(file: string, pos: SavedPosition): void {
  try {
    writeFileSync(file, JSON.stringify(pos));
  } catch {
    // A position that cannot be saved is not worth failing a drag for: it resets to the default.
  }
}
