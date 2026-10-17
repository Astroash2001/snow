import {
  type PointerEvent as ReactPointerEvent,
  useEffect,
  useLayoutEffect,
  useRef,
  useState,
  useSyncExternalStore,
} from "react";
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

export const DRAG_THRESHOLD_PX = 4; // less movement than this between press and release is a click

// Which half of its display the window is on, told by the shell. On the left half the row mirrors
// to `[orb][caption]` so the caption still grows toward the screen interior.
// The shell tells it once the page has loaded, which can be before React has mounted anything, so
// the listener is set up when this module loads and the value is read from here.
type Side = "left" | "right";
let currentSide: Side = "right";
const sideListeners = new Set<() => void>();
window.snow.chrome.onCommand((command) => {
  if (command !== "side:left" && command !== "side:right") return;
  currentSide = command === "side:left" ? "left" : "right";
  for (const listener of sideListeners) listener();
});
const useSide = (): Side =>
  useSyncExternalStore(
    (listener) => {
      sideListeners.add(listener);
      return () => sideListeners.delete(listener);
    },
    () => currentSide,
  );

// Click versus drag without a CSS drag region (those swallow clicks): the press is tracked on the
// pointer's screen position, which does not change when the window moves under it. Under 4 px at
// release it is a click and opens the dashboard; 4 px or more is a drag, reported as the total
// movement so far, and never opens the dashboard.
function useOrbPointer() {
  const press = useRef<{ x: number; y: number; dragging: boolean } | null>(null);
  const { chrome } = window.snow;
  const end = (e: ReactPointerEvent, cancelled: boolean) => {
    const p = press.current;
    if (!p) return;
    press.current = null;
    if (p.dragging) chrome.dragEnd();
    else if (!cancelled) chrome.click();
    try {
      e.currentTarget.releasePointerCapture(e.pointerId);
    } catch {
      // Not captured (a synthetic pointer): nothing to release.
    }
  };
  return {
    onPointerDown: (e: ReactPointerEvent) => {
      if (e.button !== 0) return;
      press.current = { x: e.screenX, y: e.screenY, dragging: false };
      try {
        e.currentTarget.setPointerCapture(e.pointerId);
      } catch {
        // Not capturable (a synthetic pointer): the events still arrive while over the orb.
      }
    },
    onPointerMove: (e: ReactPointerEvent) => {
      const p = press.current;
      if (!p) return;
      const dx = e.screenX - p.x;
      const dy = e.screenY - p.y;
      if (!p.dragging && Math.hypot(dx, dy) < DRAG_THRESHOLD_PX) return;
      p.dragging = true;
      chrome.drag(dx, dy);
    },
    onPointerUp: (e: ReactPointerEvent) => end(e, false),
    onPointerCancel: (e: ReactPointerEvent) => end(e, true),
  };
}

// The corner form of Snow (D-13): `[caption pill][orb]`, the orb at the screen-side edge. The window
// is click-through except the orb, so pointer enter and leave on the orb switch that off and on.
export function MiniIndicator() {
  const presence = useHud((s) => s.presence);
  const muted = useHud((s) => s.muted);
  const connection = useHud((s) => s.connection);
  const alert = useHud(selectAlert);
  const caption = useCaption();
  const side = useSide();
  const pointer = useOrbPointer();
  const online = connection === "online";
  // Before the first snapshot and while the socket is down the orb shows its offline style.
  const orbState = online ? presence : "offline";
  const showMuted = online && muted;
  const showCaption = online && !muted && presence !== "sleeping" && caption.text !== "";
  const { chrome } = window.snow;

  return (
    <div
      data-testid="mini-row"
      data-side={side}
      className={`flex h-screen items-center justify-end gap-2 ${
        side === "left" ? "flex-row-reverse pl-2" : "pr-2"
      }`}
    >
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
        {...pointer}
      >
        <Presence state={orbState} size={MINI_ORB_PX} alert={alert} fpsCap={MINI_FPS} />
      </div>
    </div>
  );
}
