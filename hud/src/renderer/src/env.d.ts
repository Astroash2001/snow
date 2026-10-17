/// <reference types="vite/client" />

// The only thing the preload script exposes to the renderer.
interface Window {
  snow: {
    hubInfo: () => Promise<{ url: string; token: string } | null>;
    /** Window chrome only; HUD data stays on the WebSocket. */
    chrome: {
      hover: (over: boolean) => void;
      click: () => void;
      drag: (dx: number, dy: number) => void;
      dragEnd: () => void;
      onVisibility: (cb: (visible: boolean) => void) => () => void;
      onCommand: (cb: (command: string) => void) => () => void;
      sendState: (state: {
        stateWord: string;
        muted: boolean;
        attention: boolean;
        online: boolean;
      }) => void;
      setIcon: (dataUrl: string) => void;
    };
  };
}
