import { GLYPHS, TINTS } from "./sphere";

export type OrbState = "sleeping" | "listening" | "thinking" | "speaking" | "muted" | "offline";
// Offline is an outline with no glyphs, so it has no atlas.
export type AtlasState = Exclude<OrbState, "offline">;
export type SizeClass = "large" | "medium" | "small";

/** Brightness levels 0 (far, dim) to 3 (near, bright). Nodes use 2-3, lines 0-1. */
export const LEVELS = 4;
const LEVEL_ALPHA = [0.6, 0.85, 0.95, 1];
// How far each level leans toward violet; the nearest level leans toward white instead.
const LEVEL_VIOLET = [0.85, 0.55, 0.15];
// A second shade per level so neighbouring glyphs do not all share one color.
const TINT_VIOLET = [0, 0.3];

const FONT_PX: Record<SizeClass, number> = { large: 9, medium: 10, small: 12 };
const FONT_FAMILY = '"JetBrains Mono", ui-monospace, monospace';

export const sizeClassOf = (size: number): SizeClass =>
  size >= 128 ? "large" : size >= 64 ? "medium" : "small";

export const atlasFont = (px: number) => `500 ${px}px ${FONT_FAMILY}`;

export function fontPx(sizeClass: SizeClass): number {
  return FONT_PX[sizeClass];
}

// Design tokens come from styles.css so no color is written twice.
export function readToken(name: string): string {
  const v = getComputedStyle(document.documentElement).getPropertyValue(name).trim();
  return v || "white";
}

function parseHex(hex: string): [number, number, number] | null {
  const m = /^#([0-9a-f]{6})$/i.exec(hex);
  if (!m) return null;
  const n = Number.parseInt(m[1], 16);
  return [(n >> 16) & 255, (n >> 8) & 255, n & 255];
}

export function mix(a: string, b: string, t: number): string {
  const pa = parseHex(a);
  const pb = parseHex(b);
  if (!pa || !pb) return a;
  const c = pa.map((v, i) => Math.round(v + (pb[i] - v) * t));
  return `rgb(${c[0]} ${c[1]} ${c[2]})`;
}

export function withAlpha(hex: string, alpha: number): string {
  const p = parseHex(hex);
  return p ? `rgb(${p[0]} ${p[1]} ${p[2]} / ${alpha})` : hex;
}

// The hue each state paints in, before depth blends it toward violet.
export function hueOf(state: AtlasState): string {
  if (state === "muted") {
    // Desaturated red: the muted token pulled toward the neutral grey token.
    return mix(readToken("--snow-state-muted"), readToken("--snow-state-offline"), 0.35);
  }
  return readToken(`--snow-state-${state}`);
}

export interface Atlas {
  canvas: OffscreenCanvas;
  cellW: number;
  cellH: number;
  hue: string;
}

// Every glyph is drawn once per (brightness level, tint) with its glow baked in, and the frame loop
// only blits cells. Row = glyph index, column = level * TINTS + tint.
export function buildAtlas(state: AtlasState, sizeClass: SizeClass, dpr = 1): Atlas {
  const px = FONT_PX[sizeClass] * dpr;
  const pad = Math.ceil(8 * dpr); // room for the glow
  const cellW = Math.ceil(px * 0.62 * 4) + pad * 2; // widest fragment is 4 characters
  const cellH = Math.ceil(px * 1.25) + pad * 2;
  const canvas = new OffscreenCanvas(cellW * LEVELS * TINTS, cellH * GLYPHS.length);
  const ctx = canvas.getContext("2d");
  if (!ctx) throw new Error("2d canvas unavailable");
  const hue = hueOf(state);
  const violet = readToken("--snow-state-thinking");
  const white = readToken("--snow-text");
  ctx.font = atlasFont(px);
  ctx.textAlign = "center";
  ctx.textBaseline = "middle";
  for (let g = 0; g < GLYPHS.length; g++) {
    for (let level = 0; level < LEVELS; level++) {
      for (let tint = 0; tint < TINTS; tint++) {
        const base =
          level === 3 ? mix(hue, white, 0.6) : mix(hue, violet, LEVEL_VIOLET[level] ?? 0);
        const color = tint === 0 ? base : mix(base, violet, TINT_VIOLET[tint]);
        ctx.globalAlpha = LEVEL_ALPHA[level];
        ctx.fillStyle = color;
        // Glow only on the brightest levels.
        ctx.shadowColor = color;
        ctx.shadowBlur = level === 3 ? 8 * dpr : level === 2 ? 4 * dpr : 0;
        ctx.fillText(
          GLYPHS[g],
          (level * TINTS + tint) * cellW + cellW / 2,
          g * cellH + cellH / 2 + px * 0.05,
        );
      }
    }
  }
  return { canvas, cellW, cellH, hue };
}
