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
