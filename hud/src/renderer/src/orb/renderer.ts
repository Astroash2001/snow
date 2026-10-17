import { LEVEL_STALE_MS, type Levels, levels as sharedLevels, TEST_MODE } from "../levels";
import {
  type Atlas,
  type AtlasState,
  atlasFont,
  buildAtlas,
  fontPx,
  type OrbState,
  readToken,
  type SizeClass,
  sizeClassOf,
  withAlpha,
} from "./atlas";
import { orbScale, Smoother } from "./smoother";
import { buildSphere, type Sphere, TINTS } from "./sphere";

export type { OrbState } from "./atlas";

const FADE_MS = 120; // UI-SPEC: the new hue is painted at once, a 120 ms cross-fade settles it
const SLEEP_FPS = 15;
const TAU = Math.PI * 2;
const FROZEN_ANGLE = 0.9;

// Per-state motion signature (UI-SPEC "Orb (Presence) Contract").
const BASE_ALPHA: Record<AtlasState, number> = {
  sleeping: 0.45,
  listening: 1,
  thinking: 1,
  speaking: 1,
  muted: 0.6,
};
// Radians per second; the sphere turns slowly, faster while thinking.
const SPIN: Record<AtlasState, number> = {
  sleeping: TAU / 60,
  listening: TAU / 40,
  thinking: TAU / 12,
  speaking: TAU / 40,
  muted: 0,
};

export interface OrbOptions {
  size: number;
  seed?: number;
  /** Highest frame rate while awake; the dashboard uses 60, the mini window 30. */
  fpsCap?: number;
  state?: OrbState;
  alert?: boolean;
  levels?: Levels;
}

export interface OrbStats {
  state: OrbState;
  alert: boolean;
  frames: number;
  avgDrawMs: number;
  atlases: number;
}

interface FrameParams {
  angle: number;
  scale: number; // 1 + 0.18 x smoothed level
  level: number;
  pulse: number; // 0..1, thinking
  sweep: number; // radians, thinking
  t: number;
}

// Every live renderer, so the test hook can reach them.
const activeOrbs = new Set<OrbRenderer>();

export class OrbRenderer {
  private readonly canvas: HTMLCanvasElement;
  private readonly ctx: CanvasRenderingContext2D;
  private readonly size: number;
  private readonly sizeClass: SizeClass;
  private readonly fpsCap: number;
  private readonly levels: Levels;
  private readonly dpr: number;
  private readonly cx: number;
  private readonly cy: number;
  private readonly radius: number;
  private readonly smoother = new Smoother();
  private readonly atlases = new Map<AtlasState, Atlas>();
  private readonly tokens: { alert: string; text: string; offline: string };
  private sphere: Sphere;
  private state: OrbState;
  private prev: OrbState | null = null;
  private fadeStart: number | null = null;
  private fadeMs = FADE_MS;
  private alert: boolean;
  private angle = 0;
  private flickerDebt = 0;
  private lastDraw = 0;
  private dirty = true;
  private frozen = false;
  private ready = false;
  private running = false;
  private raf = 0;
  private pendingSeqs: Array<number | null> = []; // events whose change is not yet painted (test runs only)
  private reduced = false;
  private drawMsTotal = 0;
  private drawFrames = 0;
  private motionQuery: MediaQueryList | null = null;

  constructor(canvas: HTMLCanvasElement, opts: OrbOptions) {
    const ctx = canvas.getContext("2d");
    if (!ctx) throw new Error("2d canvas unavailable");
    this.canvas = canvas;
    this.ctx = ctx;
    this.size = opts.size;
    this.sizeClass = sizeClassOf(opts.size);
    this.fpsCap = opts.fpsCap ?? 60;
    this.levels = opts.levels ?? sharedLevels;
    this.state = opts.state ?? "offline";
    this.alert = opts.alert ?? false;
    this.dpr = Math.max(1, window.devicePixelRatio || 1);
    this.sphere = buildSphere(opts.seed ?? 7, opts.size);
    // The bitmap is device pixels; the CSS size is set through the CSSOM, which the production CSP
    // (style-src 'self') allows, unlike a style attribute.
    const px = Math.round(opts.size * this.dpr);
    canvas.width = px;
    canvas.height = px;
    canvas.style.width = `${opts.size}px`;
    canvas.style.height = `${opts.size}px`;
    this.cx = px / 2;
    this.cy = px / 2;
    // Leaves room for the +18% swell, the listening ring and the alert dot.
    this.radius = px * 0.4;
    this.tokens = {
      alert: readToken("--snow-alert"),
      text: readToken("--snow-text"),
      offline: readToken("--snow-state-offline"),
    };
  }

  start(): void {
    if (this.running) return;
    this.running = true;
    activeOrbs.add(this);
    this.motionQuery = window.matchMedia("(prefers-reduced-motion: reduce)");
    this.reduced = this.motionQuery.matches;
    this.motionQuery.addEventListener("change", this.onMotion);
    document.addEventListener("visibilitychange", this.onVisibility);
    void this.prepare();
    this.schedule();
  }

  stop(): void {
    this.running = false;
    activeOrbs.delete(this);
    cancelAnimationFrame(this.raf);
    this.raf = 0;
    this.motionQuery?.removeEventListener("change", this.onMotion);
    document.removeEventListener("visibilitychange", this.onVisibility);
  }

  setState(state: OrbState, seq?: number | null): void {
    if (state === this.state) return;
    // Speaking to listening is a barge-in: no cross-fade wait, and the level smoother resets so
    // the orb does not ring out.
    const bargeIn = this.state === "speaking" && state === "listening";
    this.prev = bargeIn ? null : this.state;
    this.fadeStart = null;
    this.state = state;
    this.smoother.reset();
    this.dirty = true;
    if (seq !== undefined) this.pendingSeqs.push(seq);
    this.schedule();
  }

  setAlert(on: boolean): void {
    if (on === this.alert) return;
    this.alert = on;
    this.dirty = true;
    this.schedule();
  }

  /** Test hook: fixed seed, no animation. The orb draws once and stays put. */
  freeze(seed: number): void {
    this.sphere = buildSphere(seed, this.size);
    this.frozen = true;
    this.angle = FROZEN_ANGLE;
    this.prev = null;
    this.dirty = true;
    this.schedule();
  }

  stats(): OrbStats {
    return {
      state: this.state,
      alert: this.alert,
      frames: this.drawFrames,
      avgDrawMs: this.drawFrames ? this.drawMsTotal / this.drawFrames : 0,
      atlases: this.atlases.size,
    };
  }

  /** Draws one frame if one is due. `level` is the raw 0..1 level for the current state. */
  frame(now: number, level: number): boolean {
    const st = this.state;
    const isStatic = st === "muted" || st === "offline";
    if (this.prev) {
      this.fadeStart ??= now;
      if (now - this.fadeStart >= this.fadeMs) this.prev = null;
    }
    const fading = this.prev !== null;
    // Until the font and first atlas are ready there is nothing to draw but the offline outline.
    if (!this.ready && st !== "offline") return false;
    if (!this.dirty && !fading) {
      if (this.frozen || isStatic) return false;
      const cap = st === "sleeping" ? Math.min(this.fpsCap, SLEEP_FPS) : this.fpsCap;
      // 1 ms of slack: rAF timestamps jitter, and a cap should not skip a frame for 0.2 ms.
      if (now - this.lastDraw < 1000 / cap - 1) return false;
    }

    const t0 = performance.now();
    const dt = this.lastDraw === 0 ? 16 : Math.min(now - this.lastDraw, 100);
    this.lastDraw = now;
    const animated = !this.frozen && !isStatic;
    const still = this.reduced || !animated;

    let swell = 0;
    if (!this.frozen && (st === "listening" || st === "speaking")) {
      swell = this.smoother.push(level, now);
    }
    let scale = orbScale(swell, this.reduced);
    let pulse = 1;
    let sweep = 0;
    if (!this.frozen && !this.reduced) {
      if (st === "sleeping") scale = 1 + 0.03 * Math.sin((now / 6000) * TAU); // 6 s breathing
      if (st === "thinking") {
        pulse = 0.5 + 0.5 * Math.sin((now / 2400) * TAU); // 2.4 s pulse
        sweep = (now / 2400) * TAU;
      }
    }
    if (!still) {
      this.angle = (this.angle + (SPIN[st] * dt) / 1000) % TAU;
      this.flickerDebt += this.sphere.count * 0.3 * (dt / 1000); // each glyph re-rolls ~0.3 times a second
      const n = Math.floor(this.flickerDebt);
      if (n > 0) {
        this.sphere.flicker(n);
        this.flickerDebt -= n;
      }
    }

    const p: FrameParams = { angle: this.angle, scale, level: swell, pulse, sweep, t: now };
    const { ctx } = this;
    ctx.clearRect(0, 0, this.canvas.width, this.canvas.height);
    if (this.prev && this.fadeStart !== null) {
      // The new state is already fully painted; the old one fades out over it.
      this.drawState(st, 1, p);
      this.drawState(this.prev, 0.6 * (1 - (now - this.fadeStart) / this.fadeMs), p);
    } else {
      this.drawState(st, 1, p);
    }
    if (this.alert) this.drawAlert();
    ctx.globalAlpha = 1;

    this.dirty = false;
    this.drawMsTotal += performance.now() - t0;
    this.drawFrames += 1;
    // Every event that changed the state since the last paint becomes visible in this one.
    for (const seq of this.pendingSeqs) performance.mark(`paint:${seq}`);
    this.pendingSeqs.length = 0;
    return true;
  }

  // Which atlases exist is decided here: fonts first (the glyph atlas needs JetBrains Mono, which the
  // browser only loads on demand), then the current state, then the rest one per tick.
  private async prepare(): Promise<void> {
    try {
      await document.fonts.load(atlasFont(fontPx(this.sizeClass)), "0");
    } catch {
      // Fall back to the system monospace face; the orb still draws.
    }
    if (!this.running) return;
    this.ready = true;
    this.dirty = true;
    this.schedule();
    const rest: AtlasState[] = ["listening", "thinking", "speaking", "sleeping", "muted"];
    for (const s of rest) {
      await new Promise<void>((r) => setTimeout(r, 0));
      if (!this.running) return;
      this.atlasFor(s);
    }
  }

  private atlasFor(state: AtlasState): Atlas | null {
    if (!this.ready) return null;
    let a = this.atlases.get(state);
    if (!a) {
      a = buildAtlas(state, this.sizeClass, this.dpr);
      this.atlases.set(state, a);
    }
    return a;
  }

  private drawState(state: OrbState, mul: number, p: FrameParams): void {
    const { ctx, cx, cy } = this;
    const R = this.radius * p.scale;
    if (state === "offline") {
      // Dashed outline only, no fill.
      ctx.globalAlpha = mul;
      ctx.strokeStyle = this.tokens.offline;
      ctx.lineWidth = 1.5 * this.dpr;
      ctx.setLineDash([4 * this.dpr, 4 * this.dpr]);
      ctx.beginPath();
      ctx.arc(cx, cy, this.radius, 0, TAU);
      ctx.stroke();
      ctx.setLineDash([]);
      return;
    }
    const atlas = this.atlasFor(state);
    if (!atlas) return;

    if (state === "speaking") {
      // A solid, soft glow inside the orb; no ring.
      const g = ctx.createRadialGradient(cx, cy, 0, cx, cy, R * 1.05);
      g.addColorStop(0, withAlpha(atlas.hue, 0.3));
      g.addColorStop(0.7, withAlpha(atlas.hue, 0.12));
      g.addColorStop(1, withAlpha(atlas.hue, 0));
      ctx.globalAlpha = mul;
      ctx.fillStyle = g;
      ctx.beginPath();
      ctx.arc(cx, cy, R * 1.05, 0, TAU);
      ctx.fill();
    }

    const cosA = Math.cos(p.angle);
    const sinA = Math.sin(p.angle);
    const { cellW, cellH } = atlas;
    const sp = this.sphere;
    const base = BASE_ALPHA[state] * mul * (state === "thinking" ? 0.8 + 0.2 * p.pulse : 1);
    ctx.globalAlpha = base;
    for (let i = 0; i < sp.count; i++) {
      const x = sp.x[i];
      const z = sp.z[i];
      const xr = x * cosA + z * sinA;
      const zr = -x * sinA + z * cosA;
      const d = (zr + 1) * 0.5; // 1 = nearest the viewer
      const px = cx + xr * R;
      const py = cy + sp.y[i] * R;
      const node = sp.isNode[i] === 1;
      const level = node ? (d > 0.62 ? 3 : 2) : d > 0.5 ? 1 : 0;
      // Nodes are the big bright glyphs; line glyphs are small and dim; the far side recedes.
      const s = node ? 0.6 + 0.4 * d : 0.32 + 0.26 * d;
      const w = cellW * s;
      const h = cellH * s;
      let a = base * (0.4 + 0.6 * d);
      // Thinking: a gradient that rotates around the orb.
      if (state === "thinking" && !this.reduced) {
        a *= 0.55 + 0.45 * (0.5 + 0.5 * Math.cos(Math.atan2(py - cy, px - cx) - p.sweep));
      }
      ctx.globalAlpha = a;
      ctx.drawImage(
        atlas.canvas,
        (level * TINTS + sp.tint[i]) * cellW,
        sp.glyph[i] * cellH,
        cellW,
        cellH,
        px - w / 2,
        py - h / 2,
        w,
        h,
      );
    }

    if (state === "listening") {
      // A thin outer ring that expands with the mic level.
      const swell = this.reduced ? p.level / 3 : p.level;
      ctx.globalAlpha = mul * (0.25 + 0.6 * swell);
      ctx.strokeStyle = atlas.hue;
      ctx.lineWidth = this.dpr;
      ctx.beginPath();
      ctx.arc(cx, cy, this.radius * (1.04 + 0.18 * swell), 0, TAU);
      ctx.stroke();
    }
    if (state === "muted") this.drawMicSlash(mul);
  }

  // The microphone-slash glyph, drawn as paths so the frame loop never lays out text.
  private drawMicSlash(mul: number): void {
    const { ctx, cx, cy } = this;
    const u = this.radius * 0.5;
    ctx.save();
    ctx.globalAlpha = mul;
    ctx.lineCap = "round";
    ctx.lineWidth = Math.max(1.5 * this.dpr, u * 0.12);
    ctx.strokeStyle = this.tokens.text;
    ctx.beginPath();
    ctx.roundRect(cx - u * 0.28, cy - u * 0.8, u * 0.56, u, u * 0.28);
    ctx.stroke();
    ctx.beginPath();
    ctx.arc(cx, cy - u * 0.15, u * 0.55, 0.12 * Math.PI, 0.88 * Math.PI);
    ctx.stroke();
    ctx.beginPath();
    ctx.moveTo(cx, cy + u * 0.4);
    ctx.lineTo(cx, cy + u * 0.8);
    ctx.moveTo(cx - u * 0.3, cy + u * 0.8);
    ctx.lineTo(cx + u * 0.3, cy + u * 0.8);
    ctx.stroke();
    ctx.strokeStyle = this.tokens.alert;
    ctx.lineWidth *= 1.3;
    ctx.beginPath();
    ctx.moveTo(cx - u * 0.9, cy - u * 0.9);
    ctx.lineTo(cx + u * 0.9, cy + u * 0.9);
    ctx.stroke();
    ctx.restore();
  }

  // The UI-SPEC alert dot: 8 px, alert hue, on the orb's top edge, in every state.
  private drawAlert(): void {
    const { ctx } = this;
    ctx.globalAlpha = 1;
    ctx.fillStyle = this.tokens.alert;
    ctx.beginPath();
    ctx.arc(this.cx, this.cy - this.radius, 4 * this.dpr, 0, TAU);
    ctx.fill();
  }

  private readLevel(now: number): number {
    if (now - this.levels.updatedAt > LEVEL_STALE_MS) return 0;
    if (this.state === "listening") return this.levels.mic;
    if (this.state === "speaking") return this.levels.tts;
    return 0; // sleeping, thinking, muted and offline ignore audio
  }

  private readonly loop = (now: number): void => {
    this.raf = 0;
    if (!this.running || document.visibilityState === "hidden") return;
    this.raf = requestAnimationFrame(this.loop);
    this.frame(now, this.readLevel(now));
  };

  // 0 fps while the window is hidden: the loop is cancelled outright, not throttled.
  private schedule(): void {
    if (!this.running || this.raf || document.visibilityState === "hidden") return;
    this.raf = requestAnimationFrame(this.loop);
  }

  private readonly onVisibility = (): void => {
    if (document.visibilityState === "hidden") {
      cancelAnimationFrame(this.raf);
      this.raf = 0;
    } else {
      this.dirty = true;
      this.schedule();
    }
  };

  private readonly onMotion = (e: MediaQueryListEvent): void => {
    this.reduced = e.matches;
    this.dirty = true;
  };
}

export interface SnowTestHook {
  freezeOrb(seed: number): void;
  orbStats(): OrbStats | null;
}

// Exposed only when the main process added ?snowtest=1 (SNOW_HUD_TEST=1). It can freeze the orb and
// read frame counters; it holds no data and no IPC.
export function installSnowTestHook(): void {
  if (!TEST_MODE) return;
  const hook: SnowTestHook = {
    freezeOrb(seed) {
      for (const o of activeOrbs) o.freeze(seed);
    },
    orbStats() {
      const first = activeOrbs.values().next().value;
      return first ? first.stats() : null;
    },
  };
  Object.defineProperty(window, "__snowTest", { value: hook });
}
