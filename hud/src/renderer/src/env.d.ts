/// <reference types="vite/client" />

// The only thing the preload script exposes to the renderer.
interface Window {
  snow: { hubInfo: () => Promise<{ url: string; token: string } | null> };
}
