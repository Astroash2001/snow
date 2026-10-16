import "@fontsource-variable/inter";
import "./index.css";
import { createRoot } from "react-dom/client";
import { App } from "./App";
import { connectHub } from "./ws";

// biome-ignore lint/style/noNonNullAssertion: index.html always has #root
createRoot(document.getElementById("root")!).render(<App />);
void connectHub();
