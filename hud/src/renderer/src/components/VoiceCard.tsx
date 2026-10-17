import type { ReactNode } from "react";
import type { SttStatus, VoiceStatus } from "../../../generated/contracts";
import { clockTime, copy } from "../copy";
import { useHud } from "../store";
import { type ChipKind, StatusChip } from "./StatusChip";

const NUMBER = new Intl.NumberFormat("en-US"); // thousands separators, fixed so the card never reflows by locale
// shortcut: 10% of the Free plan's 20,000 monthly credits; read the plan size from Cartesia if
// plan 01-31 finds an endpoint for it.
const LOW_CREDITS = 2_000;
const HELPER = "wrap-anywhere text-xs text-(--snow-text-3)";

const ROLE_CHIP: Record<VoiceStatus["voice_role"], ChipKind> = {
  everyday: "neutral",
  big_moment: "neutral",
  gpu: "neutral",
  fallback: "fallback", // Kokoro only: the last-resort voice
};

function Row({ title, chip, children }: { title: string; chip?: ReactNode; children?: ReactNode }) {
  return (
    <div className="flex flex-col gap-1">
      <div className="flex h-6 items-center justify-between gap-2">
        <h2 className="text-xs font-semibold text-(--snow-text-3)">{title}</h2>
        {chip}
      </div>
      {children}
    </div>
  );
}

const Checking = () => <StatusChip kind="checking" label={copy.chip.checking} />;

function VoiceRow({ voice }: { voice: VoiceStatus | null }) {
  if (!voice) return <Row title={copy.voiceCard.voice} chip={<Checking />} />;
  const label = copy.voiceCard.roles[voice.voice_role];
  return (
    <Row
      title={copy.voiceCard.voice}
      chip={<StatusChip kind={ROLE_CHIP[voice.voice_role]} label={label} />}
    >
      <p className="flex min-w-0 gap-2 text-sm">
        <span data-testid="voice-engine" className="shrink-0">
          {copy.voiceCard.engines[voice.engine]}
        </span>
        <span
          data-testid="voice-name"
          title={voice.voice_name}
          className="min-w-0 truncate text-(--snow-text-2)"
        >
          {voice.voice_name}
        </span>
      </p>
    </Row>
  );
}

function CreditsRow({ voice }: { voice: VoiceStatus | null }) {
  if (!voice) {
    return (
      <Row title={copy.voiceCard.credits}>
        <p data-testid="credits-value" className="text-sm text-(--snow-text-3)">
          {copy.chip.checking}
        </p>
      </Row>
    );
  }
  const reason = voice.cartesia_reason;
  const out = reason === "out_of_credits";
  const credits = voice.credits_remaining ?? (out ? 0 : null);
  const helper = out
    ? copy.voiceOutOfCredits
    : reason === "unreachable"
      ? copy.voiceUnreachable
      : credits === null
        ? copy.creditsUnavailableHelper
        : null;
  return (
    <Row title={copy.voiceCard.credits}>
      {credits === null ? (
        <p data-testid="credits-value" className="text-sm text-(--snow-text-2)">
          {copy.creditsUnavailable}
        </p>
      ) : (
        <p
          data-testid="credits-value"
          className={`font-mono text-sm tabular-nums ${credits < LOW_CREDITS ? "text-(--snow-warn)" : "text-(--snow-text)"}`}
        >
          {NUMBER.format(credits)}
        </p>
      )}
      {helper && (
        <p data-testid="credits-helper" className={HELPER}>
          {helper}
        </p>
      )}
    </Row>
  );
}

function sttHelper(stt: SttStatus): string | null {
  if (stt.status_reason === "unreachable") return copy.sttUnreachable;
  if (stt.status_reason === "rate_limited" && stt.retry_after_ns) {
    return copy.sttLimit(clockTime(stt.retry_after_ns));
  }
  return null;
}

function SttRow({ stt }: { stt: SttStatus | null }) {
  if (!stt) return <Row title={copy.voiceCard.stt} chip={<Checking />} />;
  const primary = stt.stt_source === "groq";
  const helper = sttHelper(stt);
  return (
    <Row
      title={copy.voiceCard.stt}
      chip={
        <StatusChip
          kind={primary ? "neutral" : "fallback"}
          label={primary ? copy.voiceCard.sttPrimary : copy.voiceCard.sttFallback}
        />
      }
    >
      <p data-testid="stt-source" className="text-sm">
        {copy.voiceCard.sttSources[stt.stt_source]}
      </p>
      {helper && (
        <p data-testid="stt-helper" className={HELPER}>
          {helper}
        </p>
      )}
    </Row>
  );
}

// The Voice card: which voice spoke last, the Cartesia balance, and where the words came from
// ("Groq cloud" or "Local (Moonshine)"). The helper lines are the on-screen half of D-17; the
// spoken mention comes from the brain.
export function VoiceCard() {
  const voice = useHud((s) => s.voice);
  const stt = useHud((s) => s.stt);
  return (
    <section
      aria-label="Voice"
      data-testid="voice-card"
      className="flex flex-col gap-4 rounded-(--snow-radius-card) border border-(--snow-border) bg-(--snow-surface) p-4"
    >
      <VoiceRow voice={voice} />
      <CreditsRow voice={voice} />
      <SttRow stt={stt} />
    </section>
  );
}
