import {
  AlertTriangle,
  Check,
  CircleDashed,
  Loader,
  type LucideIcon,
  RotateCw,
  XCircle,
} from "lucide-react";

export type ChipKind =
  | "running"
  | "starting"
  | "restarting"
  | "down"
  | "active"
  | "ready"
  | "fallback"
  | "cooling"
  | "failing"
  | "notConfigured"
  | "notUsed"
  | "checking"
  | "neutral";

// Icon and text color per status. The label always travels with the icon: status is never color alone.
const LOOK: Record<ChipKind, { icon: LucideIcon; tone: string }> = {
  running: { icon: Check, tone: "text-(--snow-ok)" },
  starting: { icon: Loader, tone: "text-(--snow-text-2)" },
  restarting: { icon: RotateCw, tone: "text-(--snow-warn)" },
  down: { icon: XCircle, tone: "text-(--snow-alert)" },
  active: { icon: Check, tone: "text-(--snow-text-2)" },
  ready: { icon: Check, tone: "text-(--snow-text-2)" },
  fallback: { icon: AlertTriangle, tone: "text-(--snow-warn)" },
  cooling: { icon: AlertTriangle, tone: "text-(--snow-warn)" },
  failing: { icon: XCircle, tone: "text-(--snow-alert)" },
  notConfigured: { icon: CircleDashed, tone: "text-(--snow-text-3)" },
  notUsed: { icon: CircleDashed, tone: "text-(--snow-text-3)" },
  checking: { icon: Loader, tone: "text-(--snow-text-3)" },
  neutral: { icon: Check, tone: "text-(--snow-text-2)" },
};

// Only the icon takes the status hue; the label stays readable text so contrast holds on the card.
const TEXT: Partial<Record<ChipKind, string>> = {
  down: "text-(--snow-alert)",
  failing: "text-(--snow-alert)",
  restarting: "text-(--snow-warn)",
  fallback: "text-(--snow-warn)",
  cooling: "text-(--snow-warn)",
  notConfigured: "text-(--snow-text-3)",
  notUsed: "text-(--snow-text-3)",
  checking: "text-(--snow-text-3)",
};

interface StatusChipProps {
  kind: ChipKind;
  label: string;
}

// 24 px pill with icon and text. Keyed on kind and label, so a change remounts it and the
// `snow-fade` class cross-fades the new status in over 120 ms without moving anything.
export function StatusChip({ kind, label }: StatusChipProps) {
  const { icon: Icon, tone } = LOOK[kind];
  return (
    <span
      key={`${kind}:${label}`}
      data-testid="status-chip"
      data-kind={kind}
      className={`snow-fade inline-flex h-6 shrink-0 items-center gap-1 rounded-(--snow-radius-pill) border border-(--snow-border) px-2 text-xs font-semibold whitespace-nowrap ${TEXT[kind] ?? "text-(--snow-text-2)"}`}
    >
      <Icon aria-hidden="true" strokeWidth={1.75} className={`size-4 shrink-0 ${tone}`} />
      {label}
    </span>
  );
}
