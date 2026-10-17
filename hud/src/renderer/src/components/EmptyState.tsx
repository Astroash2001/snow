import { copy } from "../copy";
import { useHud } from "../store";

// Shown in the transcript card when there is no conversation. Which one depends on presence: a hard
// mute outranks soft sleep, which outranks plain standing by.
export function EmptyState() {
  const muted = useHud((s) => s.muted || s.presence === "muted");
  const asleep = useHud((s) => s.mode === "soft_sleep");
  const text = muted ? copy.emptyMuted : asleep ? copy.emptyAsleep : copy.emptyStandingBy;
  return (
    <div
      data-testid="empty-state"
      className="flex flex-1 flex-col items-center justify-center gap-2 p-8 text-center"
    >
      <h2 className="text-xl leading-[1.2] font-semibold text-(--snow-text)">{text.heading}</h2>
      <p className="max-w-md text-sm text-(--snow-text-2)">{text.body}</p>
    </div>
  );
}
