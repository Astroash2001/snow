import { readFileSync } from "node:fs";
import { resolve } from "node:path";
import {
  type ElectronApplication,
  _electron as electron,
  expect,
  type Page,
  test,
} from "@playwright/test";
import type {
  ChainEntryStatus,
  EventsSchema,
  HealthProvider,
  HealthRole,
  HealthSubsystem,
  Snapshot,
} from "../src/generated/contracts";
import { type MockHub, startMockHub } from "./mockHub";

const hudDir = resolve(__dirname, "..");
const base: Snapshot = JSON.parse(
  readFileSync(resolve(hudDir, "../contracts/samples/events.json"), "utf8"),
).snapshot.snapshot;

const TS = 1_760_000_000_000_000_000;

const subsystem = (
  name: string,
  label: string,
  status: HealthSubsystem["status"],
  detail: string | null = null,
): HealthSubsystem => ({
  type: "health.subsystem",
  name,
  label,
  owner: "voice",
  source: "voice",
  status,
  detail,
  ts_ns: TS,
});

const provider = (id: string, label: string, status: HealthProvider["status"]): HealthProvider => ({
  type: "health.provider",
  provider: id,
  label,
  status,
  source: "brain",
  ts_ns: TS,
});

const entry = (
  providerId: string,
  label: string,
  model: string,
  status: ChainEntryStatus["status"],
  cooling_until_ns: number | null = null,
): ChainEntryStatus => ({
  provider: providerId,
  provider_label: label,
  model,
  status,
  cooling_until_ns,
  detail: null,
});

const role = (
  name: HealthRole["role"],
  status: HealthRole["status"],
  entries: ChainEntryStatus[],
  active_index: number | null,
): HealthRole => ({
  type: "health.role",
  role: name,
  status,
  entries,
  active_index,
  active_provider: active_index === null ? null : entries[active_index].provider,
  active_model: active_index === null ? null : entries[active_index].model,
  source: "brain",
  ts_ns: TS,
});

const FIVE = [
  subsystem("wake_word", "Wake word", "running"),
  subsystem("speech_to_text", "Speech to text", "running"),
  subsystem("speech_output", "Speech output", "running"),
  subsystem("brain", "Brain", "running"),
  subsystem("event_log", "Event log", "running"),
];

const BRAIN_CHAIN = [
  entry("experiential", "Experiential Labs", "gpt-5.6-luna", "active"),
  entry("google", "Google AI Studio", "gemini-flash", "ready"),
  entry("nim", "NVIDIA NIM", "deepseek-v4-pro", "not_configured"),
  entry("openrouter", "OpenRouter", "nemotron-3-super:free", "not_configured"),
];

const HEALTHY: Partial<Snapshot> = {
  subsystems: FIVE,
  providers: [
    provider("experiential", "Experiential Labs", "active"),
    provider("groq", "Groq", "ready"),
    provider("google", "Google AI Studio", "ready"),
    provider("nim", "NVIDIA NIM", "ready"),
    provider("openrouter", "OpenRouter", "ready"),
  ],
  roles: [
    role("brain", "active", BRAIN_CHAIN, 0),
    role(
      "fast",
      "fallback",
      [
        entry("groq", "Groq", "openai/gpt-oss-120b", "cooling_down", TS + 60e9),
        entry("groq", "Groq", "qwen3.8-27b", "active"),
        entry("openrouter", "OpenRouter", "free-model", "ready"),
      ],
      1,
    ),
    role(
      "vision",
      "not_used_yet",
      [entry("experiential", "Experiential Labs", "gpt-5.6-luna", "ready")],
      null,
    ),
  ],
};

interface Ctx {
  win: Page;
  app: ElectronApplication;
  hub: MockHub;
  /** Push one event to the HUD; ts_ns and seq are filled in. */
  emit: (type: string, fields?: Record<string, unknown>) => void;
}

const launch = (hub: MockHub) =>
  electron.launch({
    args: ["."],
    cwd: hudDir,
    env: { ...process.env, SNOW_HUB_URL: hub.url, SNOW_TOKEN: hub.token },
  });

// An empty mock hub plus the real Electron HUD; both are always closed, even when the test fails.
async function withHud(snapshot: Partial<Snapshot>, run: (ctx: Ctx) => Promise<void>) {
  const hub = await startMockHub({ script: [], snapshot: { ...base, rows: [], ...snapshot } });
  const app = await launch(hub);
  try {
    const win = await app.firstWindow();
    await expect(win.getByTestId("mute-button")).toBeEnabled();
    let n = 0;
    const emit: Ctx["emit"] = (type, fields = {}) => {
      n += 1;
      hub.send({
        kind: "event",
        event: { type, source: "voice", seq: n, ts_ns: TS + n, ...fields },
      } as unknown as EventsSchema);
    };
    await run({ win, app, hub, emit });
  } finally {
    await app.close();
    await hub.close();
  }
}

const subsystemRow = (win: Page, label: string) =>
  win.getByTestId("subsystem-row").filter({ hasText: label });

test("before the first snapshot every health row says Checking, and the snapshot lands without a shift", async () => {
  const hub = await startMockHub({ script: [], snapshot: { ...base, rows: [], ...HEALTHY } });
  const { port } = hub;
  await hub.close(); // the HUD starts with nothing listening, so it has no snapshot yet
  const app = await launch(hub);
  try {
    const win = await app.firstWindow();
    const card = win.getByTestId("health-card");
    await expect(win.getByTestId("subsystem-row")).toHaveCount(5);
    const chips = card.getByTestId("status-chip");
    await expect(chips).toHaveCount(8); // five subsystem slots and three model roles
    for (const chip of await chips.all()) await expect(chip).toHaveText("Checking");

    // Each row's offset inside the card and its height, rounded: this must not change on arrival.
    const layout = () =>
      win.evaluate(() => {
        const top = document.querySelector('[data-testid="health-card"]')?.getBoundingClientRect();
        const rowSelector = ["subsystem-row", "role-brain", "role-fast", "role-vision"]
          .map((id) => `[data-testid="${id}"]`)
          .join(",");
        const rows = [...document.querySelectorAll(rowSelector)].map((el) => {
          const r = el.getBoundingClientRect();
          return [Math.round(r.top - (top?.top ?? 0)), Math.round(r.height)];
        });
        return { card: [Math.round(top?.width ?? 0), Math.round(top?.height ?? 0)], rows };
      });
    const before = await layout();

    await hub.restart(port); // the HUD's reconnect finds the hub and receives the snapshot
    await expect(win.getByTestId("mute-button")).toBeEnabled({ timeout: 20_000 });
    await expect(subsystemRow(win, "Wake word")).toContainText("Running");
    await expect(win.getByTestId("role-brain")).toContainText("Active");
    expect(await layout()).toEqual(before);
  } finally {
    await app.close();
    await hub.close();
  }
});

test("subsystem rows come from the snapshot; Down and Restarting show their chip and helper", async () => {
  const subsystems = [
    subsystem("a", "Alpha", "running"),
    subsystem("b", "Beta", "starting"),
    subsystem("c", "Gamma", "restarting"),
    subsystem("d", "Delta", "down"),
    subsystem("e", "Epsilon", "down", "No Groq key. Run snow setup."),
  ];
  await withHud({ subsystems }, async ({ win }) => {
    const rows = win.getByTestId("subsystem-row");
    await expect(rows).toHaveCount(5); // whatever the snapshot has, in order, nothing hard-coded
    await expect(rows.nth(0)).toHaveText("AlphaRunning");
    await expect(rows.nth(1)).toHaveText("BetaStarting");
    await expect(rows.nth(2)).toContainText("Restarting");
    await expect(rows.nth(2)).toContainText("Snow is restarting it automatically.");
    await expect(rows.nth(3)).toContainText("Down");
    await expect(rows.nth(3)).toContainText("Could not restart. See logs.");
    await expect(rows.nth(4)).toContainText("No Groq key. Run snow setup.");
    // Every chip carries an icon and a text label, never color alone.
    for (const chip of await win.getByTestId("subsystems").getByTestId("status-chip").all()) {
      await expect(chip.locator("svg")).toHaveCount(1);
      expect((await chip.innerText()).trim().length).toBeGreaterThan(0);
    }
  });
});

test("a delta updates the chip in place without reordering the rows", async () => {
  await withHud({ subsystems: FIVE }, async ({ win, emit }) => {
    const names = () =>
      win
        .getByTestId("subsystem-row")
        .evaluateAll((els) =>
          els.map((el) => el.firstElementChild?.firstElementChild?.textContent),
        );
    const before = await names();
    emit("health.subsystem", {
      name: "speech_to_text",
      label: "Speech to text",
      owner: "voice",
      status: "restarting",
      detail: null,
    });
    await expect(subsystemRow(win, "Speech to text")).toContainText("Restarting");
    emit("health.subsystem", {
      name: "brain",
      label: "Brain",
      owner: "brain",
      status: "down",
      detail: null,
    });
    await expect(subsystemRow(win, "Brain")).toContainText("Down");
    expect(await names()).toEqual(before);
    emit("health.subsystem", {
      name: "speech_to_text",
      label: "Speech to text",
      owner: "voice",
      status: "running",
      detail: null,
    });
    await expect(subsystemRow(win, "Speech to text")).toHaveText("Speech to textRunning");
  });
});

test("zero subsystems in the snapshot reads 'No health data yet'", async () => {
  await withHud({ subsystems: [] }, async ({ win }) => {
    await expect(win.getByTestId("no-health")).toHaveText("No health data yet");
    await expect(win.getByTestId("subsystem-row")).toHaveCount(0);
  });
});

test("three collapsed role rows show the active model and chip; expanding lists the chain", async () => {
  await withHud(HEALTHY, async ({ win }) => {
    for (const r of ["brain", "fast", "vision"]) {
      await expect(win.getByTestId(`role-${r}`).locator("button")).toHaveAttribute(
        "aria-expanded",
        "false",
      );
      await expect(win.getByTestId(`chain-${r}`)).toHaveCount(0); // collapsed by default
    }
    const brain = win.getByTestId("role-brain");
    await expect(brain).toContainText("Brain");
    await expect(brain.getByTestId("role-active")).toHaveText("Experiential Labs / gpt-5.6-luna");
    await expect(brain.getByTestId("status-chip")).toHaveText("Active");
    await expect(win.getByTestId("role-fast").getByTestId("status-chip")).toHaveText(
      "Fallback in use (2 of 3)",
    );
    await expect(win.getByTestId("role-vision").getByTestId("status-chip")).toHaveText(
      "Not used yet",
    );
    await expect(win.getByTestId("role-vision").getByTestId("role-active")).toHaveCount(0);

    await brain.locator("button").click();
    await expect(brain.locator("button")).toHaveAttribute("aria-expanded", "true");
    const chain = win.getByTestId("chain-brain").getByTestId("chain-entry");
    await expect(chain).toHaveCount(4); // in the order the hub sent them
    await expect(chain.nth(0)).toContainText("Experiential Labs");
    await expect(chain.nth(0)).toContainText("Active");
    await expect(chain.nth(1)).toContainText("Google AI Studio");
    await expect(chain.nth(1)).toContainText("Ready");
    await expect(chain.nth(2)).toContainText("Not configured");
    await expect(chain.nth(2)).toContainText("No key stored. Run snow setup to add one.");
    await expect(chain.nth(2).locator("code")).toHaveText("snow setup");

    await brain.locator("button").click();
    await expect(win.getByTestId("chain-brain")).toHaveCount(0);
  });
});

test("the remaining role chips: cooling down until a time, failing and not configured", async () => {
  const until = new Date(2026, 9, 17, 14, 5).getTime() * 1e6;
  const roles = [
    role(
      "brain",
      "cooling_down",
      [entry("experiential", "Experiential Labs", "gpt-5.6-luna", "cooling_down", until)],
      0,
    ),
    role("fast", "failing", [entry("groq", "Groq", "m", "failing")], 0),
    role(
      "vision",
      "not_configured",
      [entry("google", "Google AI Studio", "g", "not_configured")],
      null,
    ),
  ];
  await withHud({ roles }, async ({ win }) => {
    // Formatted in the renderer, which is what the HUD itself uses.
    const hhmm = await win.evaluate(
      (ms) => new Date(ms).toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" }),
      until / 1e6,
    );
    await expect(win.getByTestId("role-brain").getByTestId("status-chip")).toHaveText(
      `Cooling down until ${hhmm}`,
    );
    await expect(win.getByTestId("role-fast").getByTestId("status-chip")).toHaveText("Failing");
    await expect(win.getByTestId("role-vision").getByTestId("status-chip")).toHaveText(
      "Not configured",
    );
  });
});

test("a role the snapshot does not carry yet shows Checking in its slot", async () => {
  await withHud(
    { roles: [role("fast", "active", [entry("groq", "Groq", "m", "active")], 0)] },
    async ({ win }) => {
      await expect(win.getByTestId("role-brain").getByTestId("status-chip")).toHaveText("Checking");
      await expect(win.getByTestId("role-fast").getByTestId("status-chip")).toHaveText("Active");
      await expect(win.getByTestId("role-vision").getByTestId("status-chip")).toHaveText(
        "Checking",
      );
    },
  );
});

test("the providers summary hides at zero and keeps its wording at one and many", async () => {
  const providers = (n: number) =>
    ["a", "b", "c", "d", "e"].map((id, i) =>
      provider(id, id.toUpperCase(), i < n ? "not_configured" : "ready"),
    );
  await withHud({ providers: providers(0) }, async ({ win, emit }) => {
    const summary = win.getByTestId("providers-summary");
    await expect(win.getByTestId("health-card")).toBeVisible();
    await expect(summary).toHaveCount(0);

    emit("health.provider", { provider: "a", label: "A", status: "not_configured" });
    await expect(summary).toHaveText("1 of 5 providers not configured");
    emit("health.provider", { provider: "b", label: "B", status: "not_configured" });
    await expect(summary).toHaveText("2 of 5 providers not configured");
    emit("health.provider", { provider: "a", label: "A", status: "ready" });
    emit("health.provider", { provider: "b", label: "B", status: "ready" });
    await expect(summary).toHaveCount(0);
  });
});

test("model IDs are mono with an end ellipsis, selectable, with the full value in title", async () => {
  const long = "a-very-long-model-identifier-that-cannot-possibly-fit-in-a-narrow-column-v9000";
  const roles = [
    role("brain", "active", [entry("experiential", "Experiential Labs", long, "active")], 0),
  ];
  await withHud({ roles }, async ({ win }) => {
    const model = win.getByTestId("role-brain").getByTestId("role-active").locator("span[title]");
    await expect(model).toHaveAttribute("title", `Experiential Labs / ${long}`);
    const style = await model.evaluate((el) => {
      const s = getComputedStyle(el);
      return {
        font: s.fontFamily,
        overflow: s.textOverflow,
        select: s.userSelect,
        clipped: el.scrollWidth > el.clientWidth,
      };
    });
    expect(style.font).toContain("JetBrains Mono");
    expect(style.overflow).toBe("ellipsis");
    expect(style.select).toBe("text");
    expect(style.clipped).toBe(true);
  });
});

test("below 880 px wide the two columns stack; wider they sit side by side", async () => {
  await withHud(HEALTHY, async ({ win, app }) => {
    const resize = (w: number) =>
      app.evaluate(({ BrowserWindow }, width) => {
        BrowserWindow.getAllWindows()[0].setContentSize(width, 640);
      }, w);
    const boxes = async () => {
      const a = await win.getByTestId("subsystems").boundingBox();
      const b = await win.getByTestId("roles").boundingBox();
      return { a, b };
    };
    await resize(900);
    await expect.poll(async () => (await boxes()).b?.x).toBeGreaterThan((await boxes()).a?.x ?? 0);
    const wide = await boxes();
    expect(wide.b?.y).toBeCloseTo(wide.a?.y ?? 0, 0);

    await resize(860);
    await expect
      .poll(async () => Math.round((await boxes()).b?.x ?? -1))
      .toBe(Math.round((await boxes()).a?.x ?? -2));
    const narrow = await boxes();
    expect(narrow.b?.y).toBeGreaterThan(narrow.a?.y ?? 0);
  });
});

const voiceStatus = (fields: Record<string, unknown> = {}) => ({
  type: "voice.status",
  engine: "pocket_tts",
  voice_name: "Snow",
  voice_role: "everyday",
  cartesia_available: true,
  cartesia_reason: "ok",
  credits_remaining: 9000,
  source: "voice",
  ts_ns: TS,
  ...fields,
});

const sttStatus = (fields: Record<string, unknown> = {}) => ({
  type: "stt.status",
  stt_source: "groq",
  status_reason: "primary",
  retry_after_ns: null,
  source: "voice",
  ts_ns: TS,
  ...fields,
});

const card = (win: Page) => win.getByTestId("voice-card");

test("before the first voice.status and stt.status the Voice card says Checking", async () => {
  await withHud({ voice: null, stt: null }, async ({ win, emit }) => {
    await expect(card(win).getByTestId("status-chip")).toHaveText(["Checking", "Checking"]);
    await expect(card(win).getByTestId("credits-value")).toHaveText("Checking");
    emit("voice.status", voiceStatus());
    emit("stt.status", sttStatus());
    await expect(card(win).getByTestId("voice-engine")).toHaveText("Pocket TTS");
    await expect(card(win).getByTestId("stt-source")).toHaveText("Groq cloud");
  });
});

test("the Voice card shows the active voice, mono credits with separators and the STT source", async () => {
  const voice = voiceStatus({ credits_remaining: 12345 }) as unknown as Snapshot["voice"];
  const stt = sttStatus() as unknown as Snapshot["stt"];
  await withHud({ voice, stt }, async ({ win, emit }) => {
    await expect(card(win).getByTestId("voice-engine")).toHaveText("Pocket TTS");
    await expect(card(win).getByTestId("voice-name")).toHaveText("Snow");
    await expect(card(win)).toContainText("Everyday");
    const credits = card(win).getByTestId("credits-value");
    await expect(credits).toHaveText("12,345");
    const style = await credits.evaluate((el) => {
      const s = getComputedStyle(el);
      return { font: s.fontFamily, nums: s.fontVariantNumeric, color: s.color };
    });
    expect(style.font).toContain("JetBrains Mono");
    expect(style.nums).toContain("tabular-nums");
    expect(style.color).toBe("rgb(230, 234, 242)");
    await expect(card(win).getByTestId("stt-source")).toHaveText("Groq cloud");
    await expect(card(win)).toContainText("Primary");

    // Below 10% of the 20,000 free credits the number turns warn.
    const color = () => credits.evaluate((el) => getComputedStyle(el).color);
    emit("voice.status", voiceStatus({ credits_remaining: 1999 }));
    await expect(credits).toHaveText("1,999");
    await expect.poll(color).toBe("rgb(251, 191, 36)");
    emit("voice.status", voiceStatus({ credits_remaining: 2000 }));
    await expect.poll(color).toBe("rgb(230, 234, 242)");

    emit("voice.status", voiceStatus({ engine: "cartesia", voice_role: "big_moment" }));
    await expect(card(win).getByTestId("voice-engine")).toHaveText("Cartesia");
    await expect(card(win)).toContainText("Big moment");
    emit("voice.status", voiceStatus({ engine: "chatterbox", voice_role: "gpu" }));
    await expect(card(win).getByTestId("voice-engine")).toHaveText("Chatterbox");
    await expect(card(win)).toContainText("GPU");
    emit("voice.status", voiceStatus({ engine: "kokoro", voice_role: "fallback" }));
    await expect(card(win).getByTestId("voice-engine")).toHaveText("Kokoro");
    await expect(card(win).getByTestId("status-chip").first()).toHaveAttribute(
      "data-kind",
      "fallback",
    );
  });
});

test("a missing balance reads Unavailable; out of credits and unreachable show their helper", async () => {
  const voice = voiceStatus({ credits_remaining: null }) as unknown as Snapshot["voice"];
  await withHud({ voice }, async ({ win, emit }) => {
    const credits = card(win).getByTestId("credits-value");
    const helper = card(win).getByTestId("credits-helper");
    await expect(credits).toHaveText("Unavailable");
    await expect(helper).toHaveText("Cartesia did not report a balance.");

    emit(
      "voice.status",
      voiceStatus({
        credits_remaining: 0,
        cartesia_available: false,
        cartesia_reason: "out_of_credits",
      }),
    );
    await expect(credits).toHaveText("0");
    await expect(helper).toHaveText(
      "Cartesia credits are used up. Big moments use the everyday voice.",
    );

    emit(
      "voice.status",
      voiceStatus({
        credits_remaining: 5000,
        cartesia_available: false,
        cartesia_reason: "unreachable",
      }),
    );
    await expect(credits).toHaveText("5,000");
    await expect(helper).toHaveText("Cartesia is unreachable. Big moments use the everyday voice.");

    emit("voice.status", voiceStatus());
    await expect(helper).toHaveCount(0); // recovery is automatic and clears the line
  });
});

test("speech-to-text on the local model shows Fallback and why: unreachable, or a limit until a time", async () => {
  await withHud({ stt: sttStatus() as unknown as Snapshot["stt"] }, async ({ win, emit }) => {
    const source = card(win).getByTestId("stt-source");
    const helper = card(win).getByTestId("stt-helper");
    await expect(helper).toHaveCount(0);

    emit("stt.status", sttStatus({ stt_source: "local", status_reason: "unreachable" }));
    await expect(source).toHaveText("Local (Moonshine)");
    await expect(card(win)).toContainText("Fallback");
    await expect(helper).toHaveText("Groq speech-to-text is unreachable. Using the local model.");

    const until = TS + 90e9;
    emit(
      "stt.status",
      sttStatus({ stt_source: "local", status_reason: "rate_limited", retry_after_ns: until }),
    );
    const hhmm = await win.evaluate(
      (ms) => new Date(ms).toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" }),
      until / 1e6,
    );
    await expect(helper).toHaveText(
      `Groq speech-to-text limit reached. Using the local model until ${hhmm}.`,
    );

    emit("stt.status", sttStatus());
    await expect(source).toHaveText("Groq cloud");
    await expect(helper).toHaveCount(0);
  });
});

test("a long voice name stays on one line with an end ellipsis and the full name in title", async () => {
  const name =
    "An extraordinarily long voice name that would never fit on a single line of the card";
  const voice = voiceStatus({ voice_name: name }) as unknown as Snapshot["voice"];
  await withHud({ voice }, async ({ win }) => {
    const el = card(win).getByTestId("voice-name");
    await expect(el).toHaveAttribute("title", name);
    const s = await el.evaluate((e) => {
      const c = getComputedStyle(e);
      return {
        overflow: c.textOverflow,
        white: c.whiteSpace,
        clipped: e.scrollWidth > e.clientWidth,
      };
    });
    expect(s).toEqual({ overflow: "ellipsis", white: "nowrap", clipped: true });
  });
});

test("Tab visits Mute, the orb, the role disclosures, then Jump to latest, with the focus ring on", async () => {
  const rows: Snapshot["rows"] = Array.from({ length: 40 }, (_, i) => ({
    kind: "user",
    row_id: `r${i}`,
    text: `line ${i} `.repeat(20),
    system_event: null,
    ts_ns: TS + i,
    turn_id: `t${i}`,
    interrupted: false,
  }));
  await withHud({ ...HEALTHY, rows }, async ({ win }) => {
    await win
      .getByTestId("transcript-log")
      .locator("..")
      .evaluate((el) => {
        el.scrollTop = 0;
      });
    await expect(win.getByTestId("jump-to-latest")).toBeVisible();
    const focused = () =>
      win.evaluate(() => {
        const el = document.activeElement as HTMLElement | null;
        const ring = el ? getComputedStyle(el) : null;
        return {
          id:
            el?.getAttribute("data-testid") ??
            el?.getAttribute("aria-controls") ??
            el?.getAttribute("aria-label"),
          ring: ring
            ? [ring.outlineStyle, ring.outlineWidth, ring.outlineOffset, ring.outlineColor]
            : null,
        };
      });
    const seen: Array<string | null | undefined> = [];
    for (let i = 0; i < 7; i++) {
      await win.keyboard.press("Tab");
      const f = await focused();
      seen.push(f.id);
      // 2 px ring, 2 px offset, accent colour (the px values scale with the display, so compare them).
      expect([f.ring?.[0], f.ring?.[3]]).toEqual(["solid", "rgb(103, 232, 249)"]);
      expect(f.ring?.[1]).toBe(f.ring?.[2]);
      expect(Number.parseFloat(f.ring?.[1] ?? "0")).toBeGreaterThan(0);
    }
    expect(seen).toEqual([
      "mute-button",
      expect.stringMatching(/^Snow, /),
      "role-chain-brain",
      "role-chain-fast",
      "role-chain-vision",
      null, // the scrolled transcript itself, focusable so the keyboard can scroll it
      "jump-to-latest",
    ]);
  });
});
