import {
  Menu,
  type MenuItemConstructorOptions,
  type NativeImage,
  nativeImage,
  Tray,
} from "electron";
import { copy } from "../renderer/src/copy";

/** What the dashboard renderer last reported; the tray and the mini menu show only this. */
export interface ChromeState {
  stateWord: string;
  /** The core's confirmed hard-mute state, never what was just clicked. */
  muted: boolean;
  /** A subsystem is Down or Restarting (or a model role is Failing). */
  attention: boolean;
  /** The dashboard's socket to the core is up. Mute needs it; Quit works without it. */
  online: boolean;
}

export const INITIAL_STATE: ChromeState = {
  stateWord: "Reconnecting",
  muted: false,
  attention: false,
  online: false,
};

export type MenuAction = "open" | "mute" | "unmute" | "quit";

export const tooltipOf = (s: ChromeState): string =>
  `Snow: ${s.stateWord}${s.attention ? " (attention)" : ""}`;

// The one menu, for the tray and for the mini orb's context menu (UI-SPEC "Tray"). Unmute is by
// click only (D-10); the label comes from the confirmed state, so it flips only after mute.changed.
export function menuTemplate(
  s: ChromeState,
  run: (action: MenuAction) => void,
): MenuItemConstructorOptions[] {
  return [
    { label: "Open Snow", click: () => run("open") },
    s.muted
      ? { label: copy.unmute, enabled: s.online, click: () => run("unmute") }
      : { label: copy.mute, enabled: s.online, click: () => run("mute") },
    { type: "separator" },
    { label: "Quit Snow", click: () => run("quit") },
  ];
}

export interface SnowTray {
  /** The tooltip last set (Electron has no getter). */
  tooltip: () => string;
  update: (state: ChromeState) => void;
  setIcon: (icon: NativeImage) => void;
  /** What a left click does; also how tests click the tray. */
  click: () => void;
  destroy: () => void;
}

export function createTray(
  onOpen: () => void,
  template: (s: ChromeState) => MenuItemConstructorOptions[],
): SnowTray {
  // The orb icon arrives from the dashboard renderer a moment after launch.
  const tray = new Tray(nativeImage.createEmpty());
  let tooltip = tooltipOf(INITIAL_STATE);
  tray.on("click", onOpen);
  return {
    tooltip: () => tooltip,
    update(state) {
      tooltip = tooltipOf(state);
      tray.setToolTip(tooltip);
      tray.setContextMenu(Menu.buildFromTemplate(template(state)));
    },
    setIcon: (icon) => tray.setImage(icon),
    click: onOpen,
    destroy: () => tray.destroy(),
  };
}
