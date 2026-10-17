import { ChevronDown, ChevronRight } from "lucide-react";
import { useState } from "react";
import type {
  ChainEntryStatus,
  HealthProvider,
  HealthRole,
  HealthSubsystem,
} from "../../../generated/contracts";
import { clockTime, copy } from "../copy";
import { useHud } from "../store";
import { type ChipKind, StatusChip } from "./StatusChip";

const WRAP = "wrap-anywhere"; // overflow-wrap: anywhere, so a long message never widens the card
const HELPER = `${WRAP} text-xs text-(--snow-text-3)`;
const ROLES = ["brain", "fast", "vision"] as const;

interface Chip {
  kind: ChipKind;
  label: string;
}

const CHECKING: Chip = { kind: "checking", label: copy.chip.checking };

const SUBSYSTEM_CHIP: Record<HealthSubsystem["status"], Chip> = {
  running: { kind: "running", label: copy.chip.running },
  starting: { kind: "starting", label: copy.chip.starting },
  restarting: { kind: "restarting", label: copy.chip.restarting },
  down: { kind: "down", label: copy.chip.down },
};

// What a Down or Restarting row says under its name: the supervisor's own detail when it gave one.
function subsystemHelper(s: HealthSubsystem): string | null {
  if (s.status === "restarting") return s.detail ?? copy.subsystemRestartingHelper;
  if (s.status === "down") return s.detail ?? copy.subsystemFailedHelper;
  return null;
}

const cooling = (untilNs: number | null | undefined): Chip => ({
  kind: "cooling",
  label: untilNs ? copy.chip.coolingUntil(clockTime(untilNs)) : copy.chip.cooling,
});

function entryChip(e: ChainEntryStatus): Chip {
  switch (e.status) {
    case "active":
      return { kind: "active", label: copy.chip.active };
    case "ready":
      return { kind: "ready", label: copy.chip.ready };
    case "cooling_down":
      return cooling(e.cooling_until_ns);
    case "failing":
      return { kind: "failing", label: copy.chip.failing };
    case "not_configured":
      return { kind: "notConfigured", label: copy.notConfigured };
  }
}

function roleChip(r: HealthRole | undefined): Chip {
  if (!r) return CHECKING;
  const entries = r.entries ?? [];
  switch (r.status) {
    case "active":
      return { kind: "active", label: copy.chip.active };
    case "fallback":
      return {
        kind: "fallback",
        label: copy.chip.fallbackInUse((r.active_index ?? 0) + 1, entries.length),
      };
    case "cooling_down": {
      const times = entries.flatMap((e) => (e.cooling_until_ns ? [e.cooling_until_ns] : []));
      return cooling(times.length > 0 ? Math.min(...times) : null);
    }
    case "failing":
      return { kind: "failing", label: copy.chip.failing };
    case "not_configured":
      return { kind: "notConfigured", label: copy.notConfigured };
    case "not_used_yet":
      return { kind: "notUsed", label: copy.chip.notUsed };
  }
}

// Helper copy may hold one backticked span ("Run `snow setup` to add one."); it reads as code.
function Helper({ text }: { text: string }) {
  const [before, code, after] = text.split("`");
  return (
    <p className={HELPER}>
      {before}
      {code !== undefined && <code className="font-mono">{code}</code>}
      {after}
    </p>
  );
}

function SubsystemRow({ name, chip, helper }: { name: string; chip: Chip; helper: string | null }) {
  return (
    <li data-testid="subsystem-row">
      <div className="flex h-8 items-center justify-between gap-2">
        <span className={`${WRAP} min-w-0 text-sm`}>{name}</span>
        <StatusChip kind={chip.kind} label={chip.label} />
      </div>
      {helper && <Helper text={helper} />}
    </li>
  );
}

// Model IDs are mono with an end ellipsis; the full value is in `title` and stays selectable.
function Model({ text }: { text: string }) {
  return (
    <span
      title={text}
      className="min-w-0 flex-1 truncate font-mono text-xs text-(--snow-text-2) select-text"
    >
      {text}
    </span>
  );
}

function RoleRow({
  role,
  health,
  labelOf,
}: {
  role: (typeof ROLES)[number];
  health: HealthRole | undefined;
  labelOf: (providerId: string) => string;
}) {
  const [open, setOpen] = useState(false);
  const chip = roleChip(health);
  const entries = health?.entries ?? [];
  const active =
    health?.active_provider && health.active_model
      ? `${labelOf(health.active_provider)} / ${health.active_model}`
      : null;
  const chainId = `role-chain-${role}`;
  const Chevron = open ? ChevronDown : ChevronRight;
  return (
    <li data-testid={`role-${role}`}>
      <button
        type="button"
        aria-expanded={open}
        aria-controls={chainId}
        onClick={() => setOpen(!open)}
        className="flex h-8 w-full cursor-pointer items-center gap-2 rounded-(--snow-radius-button) border-0 bg-transparent p-0 text-left text-sm text-(--snow-text)"
      >
        <Chevron
          aria-hidden="true"
          strokeWidth={1.75}
          className="size-4 shrink-0 text-(--snow-text-3)"
        />
        <span className="w-12 shrink-0">{copy.health.roles[role]}</span>
        {active ? (
          <span className="flex min-w-0 flex-1 items-center gap-2" data-testid="role-active">
            <span aria-hidden="true" className="size-2 shrink-0 rounded-full bg-(--snow-accent)" />
            <Model text={active} />
          </span>
        ) : (
          <span className="flex-1" />
        )}
        <StatusChip kind={chip.kind} label={chip.label} />
      </button>
      {open && (
        <ul id={chainId} data-testid={`chain-${role}`} className="m-0 list-none py-1 pr-0 pl-6">
          {entries.map((e) => {
            const c = entryChip(e);
            const helper =
              e.status === "not_configured" ? copy.notConfiguredHelper : (e.detail ?? null);
            return (
              <li key={`${e.provider}/${e.model}`} data-testid="chain-entry" className="py-1">
                <div className="flex min-h-6 items-center gap-2">
                  <span className="shrink-0 text-xs text-(--snow-text-2)">{e.provider_label}</span>
                  <Model text={e.model} />
                  <StatusChip kind={c.kind} label={c.label} />
                </div>
                {helper && <Helper text={helper} />}
              </li>
            );
          })}
        </ul>
      )}
    </li>
  );
}

function notConfiguredCount(providers: HealthProvider[]): number {
  return providers.filter((p) => p.status === "not_configured").length;
}

// The Health card: Subsystems and Language models from the snapshot, updated in place by deltas.
// The summary under "Language models" reads "{n} of 5 providers not configured" and hides at zero.
// Rows come from the data (never a hard-coded list); the only fixed rows are the Checking slots
// held before the first snapshot and the three model roles.
export function HealthPanel() {
  const subsystems = useHud((s) => s.subsystems);
  const roles = useHud((s) => s.roles);
  const providers = useHud((s) => s.providers);
  const online = useHud((s) => s.connection === "online");
  const awaiting = !online && subsystems.length === 0;
  const unconfigured = notConfiguredCount(providers);

  const labelOf = (id: string) =>
    roles.flatMap((r) => r.entries ?? []).find((e) => e.provider === id)?.provider_label ??
    providers.find((p) => p.provider === id)?.label ??
    id;

  return (
    <section
      aria-label="Health"
      data-testid="health-card"
      className="grid shrink-0 gap-x-6 gap-y-4 rounded-(--snow-radius-card) border border-(--snow-border) bg-(--snow-surface) p-4 min-[880px]:grid-cols-[minmax(0,2fr)_minmax(0,3fr)]"
    >
      <div className="min-w-0">
        <div className="min-h-9">
          <h2 className="text-xs font-semibold text-(--snow-text-3)">{copy.health.subsystems}</h2>
        </div>
        <ul data-testid="subsystems" className="m-0 list-none p-0">
          {awaiting ? (
            copy.health.expectedSubsystems.map((name) => (
              <SubsystemRow key={name} name={name} chip={CHECKING} helper={null} />
            ))
          ) : subsystems.length === 0 ? (
            <li
              data-testid="no-health"
              className="flex h-8 items-center text-sm text-(--snow-text-3)"
            >
              {copy.health.noHealthData}
            </li>
          ) : (
            subsystems.map((s) => (
              <SubsystemRow
                key={s.name}
                name={s.label}
                chip={SUBSYSTEM_CHIP[s.status]}
                helper={subsystemHelper(s)}
              />
            ))
          )}
        </ul>
      </div>
      <div className="min-w-0">
        <div className="min-h-9">
          <h2 className="text-xs font-semibold text-(--snow-text-3)">
            {copy.health.languageModels}
          </h2>
          {unconfigured > 0 && (
            <p data-testid="providers-summary" className="text-xs text-(--snow-text-3)">
              {copy.health.providersNotConfigured(unconfigured, copy.health.providerTotal)}
            </p>
          )}
        </div>
        <ul data-testid="roles" className="m-0 list-none p-0">
          {ROLES.map((role) => (
            <RoleRow
              key={role}
              role={role}
              health={roles.find((r) => r.role === role)}
              labelOf={labelOf}
            />
          ))}
        </ul>
      </div>
    </section>
  );
}
