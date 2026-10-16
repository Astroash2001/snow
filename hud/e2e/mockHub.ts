import { readFileSync } from "node:fs";
import type { AddressInfo } from "node:net";
import { resolve } from "node:path";
import { WebSocket, WebSocketServer } from "ws";
import type { EventsSchema, Snapshot } from "../src/generated/contracts";

const samples = resolve(__dirname, "../../contracts/samples");

const defaultSnapshot = (): Snapshot =>
  JSON.parse(readFileSync(resolve(samples, "events.json"), "utf8")).snapshot.snapshot;

const defaultScript = (): EventsSchema[] =>
  readFileSync(resolve(samples, "conversation-12.jsonl"), "utf8")
    .split("\n")
    .filter((l) => l.trim() !== "")
    .map((l) => JSON.parse(l));

export interface MockHubOptions {
  token?: string;
  snapshot?: Snapshot;
  /** Messages replayed after the snapshot, one per intervalMs. Pass [] to drive the hub with send(). */
  script?: EventsSchema[];
  intervalMs?: number;
}

export interface MockHub {
  url: string;
  token: string;
  port: number;
  /** Every frame a client sent, hello included, in arrival order. */
  received: unknown[];
  /** Push a frame to every connected client. */
  send: (msg: EventsSchema) => void;
  close: () => Promise<void>;
  /** Stop and listen again (a new port unless one is given); the old clients are dropped. */
  restart: (port?: number) => Promise<void>;
}

// Specs add behaviour by passing a script or calling send(); they never edit this file.
export async function startMockHub(opts: MockHubOptions = {}): Promise<MockHub> {
  const token = opts.token ?? "mock-token";
  const intervalMs = opts.intervalMs ?? 50;
  const snapshot = opts.snapshot ?? defaultSnapshot();
  const script = opts.script ?? defaultScript();
  const received: unknown[] = [];
  const authed = new Set<WebSocket>();
  const listen = (port: number) =>
    new Promise<WebSocketServer>((done) => {
      const server: WebSocketServer = new WebSocketServer({ host: "127.0.0.1", port }, () =>
        done(server),
      );
      server.on("connection", (ws) => {
        let timer: NodeJS.Timeout | undefined;
        ws.on("close", () => {
          clearTimeout(timer);
          authed.delete(ws);
        });
        ws.once("message", (raw) => {
          const hello = JSON.parse(String(raw));
          received.push(hello);
          if (hello.token !== token) return ws.close(4401, "bad token");
          authed.add(ws);
          ws.send(JSON.stringify({ kind: "snapshot", snapshot }));
          ws.on("message", (m) => received.push(JSON.parse(String(m))));
          let i = 0;
          const tick = () => {
            if (i >= script.length || ws.readyState !== WebSocket.OPEN) return;
            ws.send(JSON.stringify(script[i++]));
            timer = setTimeout(tick, intervalMs);
          };
          timer = setTimeout(tick, intervalMs);
        });
      });
    });

  const stop = () =>
    new Promise<void>((done) => {
      for (const ws of wss.clients) ws.terminate();
      authed.clear();
      wss.close(() => done());
    });

  let wss = await listen(0);
  const hub: MockHub = {
    url: "",
    token,
    port: 0,
    received,
    send: (msg) => {
      for (const ws of authed) ws.send(JSON.stringify(msg));
    },
    close: stop,
    restart: async (port = 0) => {
      await stop();
      wss = await listen(port);
      hub.port = (wss.address() as AddressInfo).port;
      hub.url = `ws://127.0.0.1:${hub.port}`;
    },
  };
  hub.port = (wss.address() as AddressInfo).port;
  hub.url = `ws://127.0.0.1:${hub.port}`;
  return hub;
}
