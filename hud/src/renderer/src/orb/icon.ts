import { type AtlasState, hueOf, mix, type OrbState, readToken, withAlpha } from "./atlas";
import { buildSphere } from "./sphere";

const SEED = 7;
const ANGLE = 0.9; // the orb's resting turn, so every icon is the same sphere
const TAU = Math.PI * 2;

/**
 * A tiny still of the orb as a PNG data URL, for the tray and the window icons (D-31): the nodes
 * and a few line points of the sphere in the state's hue, brighter toward the viewer. A muted orb
 * is drawn in the muted hue with a slash across it; an offline one is the dashed outline.
 */
export async function renderOrbIcon(
  state: OrbState,
  size: number,
  muted: boolean,
): Promise<string> {
  const canvas = new OffscreenCanvas(size, size);
  const ctx = canvas.getContext("2d");
  if (!ctx) throw new Error("2d canvas unavailable");
  const u = size / 16; // everything below is drawn for 16 px and scaled
  const cx = size / 2;
  const cy = size / 2;
  const R = size * 0.42;

  if (state === "offline" && !muted) {
    ctx.strokeStyle = readToken("--snow-state-offline");
    ctx.lineWidth = 1.4 * u;
    ctx.setLineDash([2.5 * u, 2.5 * u]);
    ctx.beginPath();
    ctx.arc(cx, cy, R, 0, TAU);
    ctx.stroke();
  } else {
    const drawn: AtlasState = muted ? "muted" : (state as AtlasState);
    const hue = hueOf(drawn);
    const white = readToken("--snow-text");
    const sphere = buildSphere(SEED, 16);
    const cos = Math.cos(ANGLE);
    const sin = Math.sin(ANGLE);
    // Far points first, so the near ones sit on top.
    const order = Array.from({ length: sphere.count }, (_, i) => i);
    const depth = (i: number) => (-sphere.x[i] * sin + sphere.z[i] * cos + 1) / 2;
    order.sort((a, b) => depth(a) - depth(b));
    const base = drawn === "sleeping" ? 0.6 : 1;
    for (const i of order) {
      const d = depth(i);
      const x = cx + (sphere.x[i] * cos + sphere.z[i] * sin) * R;
      const y = cy + sphere.y[i] * R;
      const node = sphere.isNode[i] === 1;
      if (node) {
        ctx.fillStyle = withAlphaOf(
          d > 0.62 ? mix(hue, white, 0.6) : hue,
          base * (0.45 + 0.55 * d),
        );
        ctx.beginPath();
        ctx.arc(x, y, (0.55 + 0.55 * d) * u, 0, TAU);
        ctx.fill();
      } else if (d > 0.35) {
        // A line point: a dim speck, only on the near half so the icon does not turn to mush.
        ctx.fillStyle = withAlphaOf(hue, base * 0.4 * d);
        ctx.fillRect(x - 0.3 * u, y - 0.3 * u, 0.6 * u, 0.6 * u);
      }
    }
  }

  if (muted) {
    // A dark underlay keeps the slash readable over bright nodes.
    ctx.lineCap = "round";
    ctx.strokeStyle = "rgb(0 0 0 / 0.7)";
    ctx.lineWidth = 3.2 * u;
    slash(ctx, cx, cy, R);
    ctx.strokeStyle = readToken("--snow-alert");
    ctx.lineWidth = 1.8 * u;
    slash(ctx, cx, cy, R);
  }

  return blobToDataUrl(await canvas.convertToBlob({ type: "image/png" }));
}

// A hue is a token hex or an "rgb(r g b)" string from mix(); either gets an alpha.
function withAlphaOf(color: string, alpha: number): string {
  const a = Math.min(Math.max(alpha, 0), 1);
  const m = /^rgb\((\d+) (\d+) (\d+)\)$/.exec(color);
  return m ? `rgb(${m[1]} ${m[2]} ${m[3]} / ${a})` : withAlpha(color, a);
}

function slash(ctx: OffscreenCanvasRenderingContext2D, cx: number, cy: number, r: number): void {
  ctx.beginPath();
  ctx.moveTo(cx - r, cy - r);
  ctx.lineTo(cx + r, cy + r);
  ctx.stroke();
}

function blobToDataUrl(blob: Blob): Promise<string> {
  return new Promise((resolve, reject) => {
    const reader = new FileReader();
    reader.onload = () => resolve(String(reader.result));
    reader.onerror = () => reject(reader.error);
    reader.readAsDataURL(blob);
  });
}
