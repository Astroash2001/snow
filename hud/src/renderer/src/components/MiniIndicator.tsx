import { useEffect, useLayoutEffect, useRef, useState } from "react";
import type { TranscriptRow } from "../../../generated/contracts";
import { copy } from "../copy";
import { selectAlert, useHud } from "../store";
import { Presence } from "./Presence";

export const CAPTION_HOLD_MS = 2500; // the caption stays this long after the final transcript
export const CAPTION_FADE_MS = 400;
const MINI_ORB_PX = 40;
const MINI_FPS = 30;

const PILL =
  "flex h-8 items-center rounded-(--snow-radius-pill) border border-(--snow-border) bg-(--snow-surface) px-4 py-2 text-sm";

const lastUser = (rows: TranscriptRow[]): TranscriptRow | null => {
  for (let i = rows.length - 1; i >= 0; i--) if (rows[i].kind === "user") return rows[i];
  return null;
};

interface Caption {
  text: string;
  fading: boolean;
}
const NO_CAPTION: Caption = { text: "", fading: false };

// What Snow heard, from live events only: the first partial of a turn shows it, each partial
// replaces it in place, the final holds for 2.5 s and then fades out over 400 ms. The state that
// arrives with a snapshot is never captioned: it is not something that was just said.
function useCaption(): Caption {
  const [caption, setCaption] = useState<Caption>(NO_CAPTION);
  useEffect(() => {
    let hold: ReturnType<typeof setTimeout> | undefined;
    let clear: ReturnType<typeof setTimeout> | undefined;
    const stop = () => {
      clearTimeout(hold);
      clearTimeout(clear);
    };
    const show = (text: string) => {
      stop();
      setCaption({ text, fading: false });
    };
    const hide = () => {
      stop();
      setCaption(NO_CAPTION);
    };
    const unsubscribe = useHud.subscribe((s, prev) => {
      if (s.connection !== "online") {
        if (prev.connection === "online") hide();
        return;
      }
      if (prev.connection !== "online") return; // the snapshot that brought us online
      if (s.partial !== prev.partial && s.partial && s.partial.text.trim() !== "") {
        show(s.partial.text);
        return;
      }
      const user = lastUser(s.rows);
      const before = lastUser(prev.rows);
      if (user && (user.row_id !== before?.row_id || user.text !== before.text)) {
        show(user.text);
        hold = setTimeout(() => {
          setCaption({ text: user.text, fading: true });
          clear = setTimeout(() => setCaption(NO_CAPTION), CAPTION_FADE_MS);
        }, CAPTION_HOLD_MS);
      }
    });
    return () => {
      unsubscribe();
      stop();
    };
  }, []);
  return caption;
}

// One line, newest words visible: the text is end-aligned inside a clipping box, and only when it
// overflows does a 24 px mask fade the left edge.
function CaptionPill({ caption }: { caption: Caption }) {
  const box = useRef<HTMLSpanElement>(null);
  const text = useRef<HTMLSpanElement>(null);
  const [overflow, setOverflow] = useState(false);
  // biome-ignore lint/correctness/useExhaustiveDependencies: re-measure whenever the words change
  useLayoutEffect(() => {
    if (box.current && text.current) {
      setOverflow(text.current.offsetWidth > box.current.clientWidth);
    }
  }, [caption.text]);
  return (
    <div
      data-testid="mini-caption"
      data-fading={caption.fading}
      className={`${PILL} snow-fade max-w-64 text-(--snow-text) transition-opacity motion-reduce:transition-none ${
        caption.fading
          ? "opacity-0 duration-(--snow-duration-slow)"
          : "opacity-100 duration-(--snow-duration-fast)"
      }`}
    >
      <span
        ref={box}
        className={`flex min-w-0 flex-1 justify-end overflow-hidden ${
          overflow ? "mask-[linear-gradient(to_right,transparent,black_24px)]" : ""
        }`}
      >
        <span ref={text} className="shrink-0 whitespace-nowrap">
          {caption.text}
        </span>
      </span>
    </div>
  );
}

// The corner form of Snow (D-13): `[caption pill][orb]`, the orb at the screen-side edge. The window
// is click-through except the orb, so pointer enter and leave on the orb switch that off and on.
export function MiniIndicator() {
  const presence = useHud((s) => s.presence);
  const muted = useHud((s) => s.muted);
  const connection = useHud((s) => s.connection);
  const alert = useHud(selectAlert);
  const caption = useCaption();
  const online = connection === "online";
  // Before the first snapshot and while the socket is down the orb shows its offline style.
  const orbState = online ? presence : "offline";
  const showMuted = online && muted;
  const showCaption = online && !muted && presence !== "sleeping" && caption.text !== "";
  const { chrome } = window.snow;

  return (
    <div className="flex h-screen items-center justify-end gap-2 pr-2">
      {showMuted && (
        <div
          data-testid="mini-muted"
          className={`${PILL} border-(--snow-alert) font-semibold text-(--snow-alert)`}
        >
          {copy.muted}
        </div>
      )}
      {showCaption && <CaptionPill caption={caption} />}
      <div
        data-testid="mini-orb"
        onPointerEnter={() => chrome.hover(true)}
        onPointerLeave={() => chrome.hover(false)}
      >
        <Presence
          state={orbState}
          size={MINI_ORB_PX}
          alert={alert}
          fpsCap={MINI_FPS}
          onClick={() => chrome.click()}
        />
      </div>
    </div>
  );
}
