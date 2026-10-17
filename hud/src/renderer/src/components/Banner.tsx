import type { LucideIcon } from "lucide-react";
import type { ReactNode } from "react";

interface BannerProps {
  icon: LucideIcon;
  /** Heading line; omit for a single-sentence banner. */
  title?: string;
  testId: string;
  /** A button on the right, such as "Unmute microphone". */
  action?: ReactNode;
  children: ReactNode;
}

// The full-width row above both columns for the two global conditions (hard mute and connection
// lost). It pushes content down and never overlays. Screen readers hear these conditions from the
// status region in App, so the banner carries no live role of its own.
export function Banner({ icon: Icon, title, testId, action, children }: BannerProps) {
  return (
    <div
      data-testid={testId}
      className="mx-4 mt-4 flex items-center gap-4 rounded-(--snow-radius-card) border border-(--snow-alert) bg-(--snow-alert-tint) p-4"
    >
      <Icon aria-hidden="true" className="size-6 shrink-0 text-(--snow-alert)" />
      <div className="min-w-0 flex-1">
        {title && (
          <h2 className="text-xl leading-[1.2] font-semibold text-(--snow-text)">{title}</h2>
        )}
        <p className={title ? "mt-1 text-sm text-(--snow-text-2)" : "text-sm text-(--snow-text)"}>
          {children}
        </p>
      </div>
      {action}
    </div>
  );
}
