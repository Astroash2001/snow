import "@fontsource-variable/inter";
import "@fontsource/jetbrains-mono/400.css";
import "./styles.css";
import { createRoot } from "react-dom/client";
import { MiniIndicator } from "./components/MiniIndicator";
import { installSnowTestHook } from "./orb/renderer";
import { connectHub } from "./ws";

installSnowTestHook();

// The mini window is a second HUD client: its own socket, its own copy of the state.
// biome-ignore lint/style/noNonNullAssertion: mini.html always has #root
createRoot(document.getElementById("root")!).render(<MiniIndicator />);
connectHub();
