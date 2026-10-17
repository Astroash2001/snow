// Glyphs the orb is built from: ASCII symbols, digits and short code fragments (UI-SPEC, D-12).
// Lines use only the single characters; the fragments are for nodes.
const SINGLES = "01{}()[]<>=+-*/|;:.#$%&@~^?!_23456789".split("");
const FRAGMENTS = ["for", "{}", "=>", "0x", "json", "fn", "if", "1", "0"];
export const GLYPHS: readonly string[] = [...SINGLES, ...FRAGMENTS];

export const TINTS = 2;

export interface Sphere {
  count: number;
  /** Unit-sphere positions; the first `nodes` points are nodes, the rest sit along edges. */
  x: Float32Array;
  y: Float32Array;
  z: Float32Array;
  nodes: number;
  isNode: Uint8Array;
  glyph: Uint8Array;
  tint: Uint8Array;
  /** Re-rolls `n` random glyphs (the low-rate flicker). */
  flicker(n: number): void;
}

// mulberry32: a small seeded generator so a seed always gives the same orb.
function rng(seed: number): () => number {
  let a = seed >>> 0;
  return () => {
    a = (a + 0x6d2b79f5) >>> 0;
    let t = a;
    t = Math.imul(t ^ (t >>> 15), t | 1);
    t ^= t + Math.imul(t ^ (t >>> 7), t | 61);
    return ((t ^ (t >>> 14)) >>> 0) / 4294967296;
  };
}

// About 220 nodes at the 192 px dashboard size, 36 at the 40 px mini size.
export function nodeCount(size: number): number {
  return size >= 128 ? 220 : size >= 64 ? 90 : 36;
}

function edgeSamples(chord: number, size: number): number {
  if (size < 64) return 1;
  return Math.max(2, Math.min(4, Math.round(chord / 0.09)));
}

export function buildSphere(seed: number, size: number): Sphere {
  const rand = rng(seed);
  const n = nodeCount(size);
  const px = new Float32Array(n);
  const py = new Float32Array(n);
  const pz = new Float32Array(n);
  const golden = Math.PI * (3 - Math.sqrt(5));
  for (let i = 0; i < n; i++) {
    // Fibonacci sphere, nudged by the seed so different seeds are different orbs.
    const y = 1 - (2 * (i + 0.5)) / n;
    const r = Math.sqrt(1 - y * y);
    const th = i * golden;
    let x = Math.cos(th) * r + (rand() - 0.5) * 0.04;
    let yy = y + (rand() - 0.5) * 0.04;
    let z = Math.sin(th) * r + (rand() - 0.5) * 0.04;
    const len = Math.hypot(x, yy, z);
    x /= len;
    yy /= len;
    z /= len;
    px[i] = x;
    py[i] = yy;
    pz[i] = z;
  }

  // Each node connects to its 3 nearest neighbours; an undirected edge is kept once.
  const edges = new Map<number, [number, number]>();
  const order = new Array<number>(n);
  for (let i = 0; i < n; i++) {
    for (let j = 0; j < n; j++) order[j] = j;
    const d2 = (j: number) => (px[i] - px[j]) ** 2 + (py[i] - py[j]) ** 2 + (pz[i] - pz[j]) ** 2;
    order.sort((a, b) => d2(a) - d2(b));
    for (let k = 1; k <= 3; k++) {
      const j = order[k];
      const a = Math.min(i, j);
      const b = Math.max(i, j);
      edges.set(a * n + b, [a, b]);
    }
  }

  const xs: number[] = Array.from(px);
  const ys: number[] = Array.from(py);
  const zs: number[] = Array.from(pz);
  for (const [a, b] of edges.values()) {
    const chord = Math.hypot(px[a] - px[b], py[a] - py[b], pz[a] - pz[b]);
    const s = edgeSamples(chord, size);
    for (let k = 1; k <= s; k++) {
      const t = k / (s + 1);
      const x = px[a] * (1 - t) + px[b] * t;
      const y = py[a] * (1 - t) + py[b] * t;
      const z = pz[a] * (1 - t) + pz[b] * t;
      const len = Math.hypot(x, y, z); // back onto the sphere, so lines hug the surface
      xs.push(x / len);
      ys.push(y / len);
      zs.push(z / len);
    }
  }

  const count = xs.length;
  // Nodes are mostly single characters with the odd code fragment; lines only single characters.
  const pick = (node: boolean) =>
    node && rand() < 0.3
      ? SINGLES.length + Math.floor(rand() * FRAGMENTS.length)
      : Math.floor(rand() * SINGLES.length);
  const isNode = new Uint8Array(count);
  isNode.fill(1, 0, n);
  const glyph = new Uint8Array(count);
  const tint = new Uint8Array(count);
  for (let i = 0; i < count; i++) {
    glyph[i] = pick(i < n);
    tint[i] = Math.floor(rand() * TINTS);
  }
  return {
    count,
    x: Float32Array.from(xs),
    y: Float32Array.from(ys),
    z: Float32Array.from(zs),
    nodes: n,
    isNode,
    glyph,
    tint,
    flicker(k: number) {
      for (let i = 0; i < k; i++) {
        const at = Math.floor(rand() * count);
        glyph[at] = pick(at < n);
      }
    },
  };
}
