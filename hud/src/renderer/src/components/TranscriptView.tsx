import { AlertTriangle, RotateCw, XCircle } from "lucide-react";
import { useCallback, useEffect, useLayoutEffect, useRef, useState } from "react";
import type { TranscriptRow } from "../../../generated/contracts";
import { copy, systemRowText } from "../copy";
import { OrbRenderer } from "../orb/renderer";
import { useHud } from "../store";
import { EmptyState } from "./EmptyState";

export const END_HOLD_MS = 2000; // the transcript stays readable this long after the conversation ends
export const END_FADE_MS = 300;
const FOLLOW_SLACK_PX = 24;
const AVATAR_PX = 16;
const AVATAR_SEED = 7;

// One frozen 16 px orb, painted once and copied onto every Snow row, so a long conversation does not
// build a glyph atlas per row. Not cached when it fails, so a later row can try again.
let avatarSource: Promise<HTMLCanvasElement> | null = null;
function paintedAvatar(): Promise<HTMLCanvasElement> {
  avatarSource ??= (async () => {
    const canvas = document.createElement("canvas");
    const orb = new OrbRenderer(canvas, { size: AVATAR_PX, seed: AVATAR_SEED, state: "sleeping" });
    orb.freeze(AVATAR_SEED);
    orb.start();
    // The first frame waits on the font load; setTimeout, not rAF, so a hidden window still gets here.
    for (let i = 0; i < 100 && orb.stats().frames === 0; i++) {
      await new Promise((r) => setTimeout(r, 20));
    }
    orb.stop();
    if (orb.stats().frames === 0) throw new Error("avatar not painted");
    return canvas;
  })().catch((err) => {
    avatarSource = null;
    throw err;
  });
  return avatarSource;
}

function SnowAvatar() {
  const ref = useRef<HTMLCanvasElement>(null);
  useEffect(() => {
    let live = true;
    paintedAvatar()
      .then((src) => {
        const canvas = ref.current;
        const ctx = canvas?.getContext("2d");
        if (!live || !canvas || !ctx) return;
        canvas.width = src.width;
        canvas.height = src.height;
        ctx.drawImage(src, 0, 0);
      })
      .catch(() => {
        // The avatar is decoration; the "Snow" label still names the speaker.
      });
    return () => {
      live = false;
    };
  }, []);
  return (
    <span aria-hidden="true" className="block size-4">
      <canvas ref={ref} data-testid="snow-avatar" className="size-4" />
    </span>
  );
}

const timeOf = (row: TranscriptRow): string =>
  new Date(row.ts_ns / 1e6).toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" });

const LABEL = "text-xs font-semibold text-(--snow-text-3)";
// Timestamps show on hover or while focus is inside the row.
const STAMP =
  "font-mono text-xs text-(--snow-text-3) opacity-0 group-focus-within:opacity-100 group-hover:opacity-100";
const WRAP = "wrap-anywhere"; // overflow-wrap: anywhere, so a long token never widens the card

function UserRow({ row }: { row: TranscriptRow }) {
  return (
    <div data-testid="row-user" className="group flex flex-col items-end gap-1">
      <span className={LABEL}>You</span>
      <p
        className={`${WRAP} max-w-[80%] rounded-(--snow-radius-card) border border-(--snow-border) bg-(--snow-bg) px-3 py-2 text-(--snow-text)`}
      >
        {row.text}
      </p>
      <time aria-hidden="true" className={STAMP}>
        {timeOf(row)}
      </time>
    </div>
  );
}

function SnowRow({ row, streaming }: { row: TranscriptRow; streaming: boolean }) {
  return (
    <div
      data-testid="row-snow"
      data-interrupted={row.interrupted ? "true" : undefined}
      aria-busy={streaming || undefined}
      className="group flex flex-col items-start gap-1"
    >
      <div className="flex items-center gap-2">
        <SnowAvatar />
        <span className={LABEL}>Snow</span>
        {row.interrupted && (
          <span className="rounded-(--snow-radius-pill) border border-(--snow-border) px-2 text-xs text-(--snow-text-2)">
            {copy.interrupted}
          </span>
        )}
      </div>
      <p className={`${WRAP} ${row.interrupted ? "text-(--snow-text-2)" : "text-(--snow-text)"}`}>
        {row.text}
      </p>
      <time aria-hidden="true" className={STAMP}>
        {timeOf(row)}
      </time>
    </div>
  );
}

function SystemRow({ row }: { row: TranscriptRow }) {
  const providers = useHud((s) => s.providers);
  const label = (id: string) => providers.find((p) => p.provider === id)?.label ?? id;
  const kind = row.system_event;
  // Every status has an icon, never color alone.
  const [Icon, tone] =
    kind === "llm.exhausted"
      ? [XCircle, "text-(--snow-alert)"]
      : kind === "llm.blocked_privacy"
        ? [AlertTriangle, "text-(--snow-warn)"]
        : [RotateCw, "text-(--snow-text-2)"];
  return (
    <div
      data-testid="row-system"
      className="flex items-start justify-center gap-2 text-center text-xs text-(--snow-text-2)"
    >
      <Icon aria-hidden="true" className={`mt-0.5 size-4 shrink-0 ${tone}`} />
      <span className={WRAP}>{systemRowText(kind, row.text, label)}</span>
    </div>
  );
}

// The chat list for the current conversation: newest at the bottom, live words in the partial row,
// Snow's reply growing delta by delta. Every string is a React text node.
export function TranscriptView() {
  const rows = useHud((s) => s.rows);
  const partial = useHud((s) => s.partial);
  const ended = useHud((s) => s.ended);
  const streaming = useHud((s) => s.streaming);
  const clearTranscript = useHud((s) => s.clearTranscript);
  const scroller = useRef<HTMLDivElement>(null);
  const [following, setFollowing] = useState(true);
  const [fading, setFading] = useState(false);

  // conversation.ended: hold, fade, then clear. A new conversation clears at once in the store and
  // flips `ended` back, which cancels these timers.
  useEffect(() => {
    if (!ended) {
      setFading(false);
      return;
    }
    let clearTimer: ReturnType<typeof setTimeout> | undefined;
    const fadeTimer = setTimeout(() => {
      setFading(true);
      clearTimer = setTimeout(clearTranscript, END_FADE_MS);
    }, END_HOLD_MS);
    return () => {
      clearTimeout(fadeTimer);
      clearTimeout(clearTimer);
    };
  }, [ended, clearTranscript]);

  const toBottom = useCallback(() => {
    const el = scroller.current;
    if (el) el.scrollTop = el.scrollHeight;
  }, []);

  const onScroll = () => {
    const el = scroller.current;
    if (el) setFollowing(el.scrollHeight - el.scrollTop - el.clientHeight <= FOLLOW_SLACK_PX);
  };

  // Follow new content only while the reader is at the bottom; an empty list resets to following.
  useLayoutEffect(() => {
    if (rows.length === 0 && !partial) setFollowing(true);
    else if (following) toBottom();
  }, [rows, partial, following, toBottom]);

  const empty = rows.length === 0 && !partial;

  return (
    <section
      aria-label="Transcript"
      className="relative flex min-h-60 flex-1 flex-col overflow-hidden rounded-(--snow-radius-card) border border-(--snow-border) bg-(--snow-surface)"
    >
      {empty ? (
        <EmptyState />
      ) : (
        <div
          ref={scroller}
          onScroll={onScroll}
          data-fading={fading}
          className={`flex-1 overflow-y-auto p-4 transition-opacity duration-300 motion-reduce:transition-none ${fading ? "opacity-0" : "opacity-100"}`}
        >
          <div
            role="log"
            aria-live="polite"
            aria-label="Conversation"
            data-testid="transcript-log"
            className="flex flex-col gap-4"
          >
            {rows.map((row) =>
              row.kind === "user" ? (
                <UserRow key={row.row_id} row={row} />
              ) : row.kind === "snow" ? (
                <SnowRow key={row.row_id} row={row} streaming={row.row_id === streaming} />
              ) : (
                <SystemRow key={row.row_id} row={row} />
              ),
            )}
          </div>
          {partial && partial.text.trim() !== "" && (
            // Outside the log: partials are never announced.
            <div data-testid="row-partial" className="mt-4 flex flex-col items-end gap-1">
              <span className={LABEL}>You</span>
              <p
                className={`${WRAP} max-w-[80%] rounded-(--snow-radius-card) border border-(--snow-border) bg-(--snow-bg) px-3 py-2 text-(--snow-text-2)`}
              >
                <span className="underline decoration-(--snow-accent) underline-offset-4">
                  {partial.text}
                </span>
                <span
                  aria-hidden="true"
                  className="ml-0.5 inline-block h-[1em] w-0.5 translate-y-0.5 bg-(--snow-accent)"
                />
              </p>
            </div>
          )}
        </div>
      )}
      {!empty && !following && (
        <button
          type="button"
          data-testid="jump-to-latest"
          onClick={() => {
            toBottom();
            setFollowing(true);
          }}
          className="absolute bottom-4 left-1/2 -translate-x-1/2 cursor-pointer rounded-(--snow-radius-button) border border-(--snow-border) bg-(--snow-surface) px-3 py-1 text-xs font-semibold text-(--snow-text)"
        >
          {copy.jumpToLatest}
        </button>
      )}
    </section>
  );
}
