// The host bridge — the one seam a view shares no matter what framework it is
// built with. A view runs in a sandboxed iframe and talks to its host over the
// MCP Apps `ui/*` JSON-RPC-over-postMessage protocol, via the standard SDK
// (`@modelcontextprotocol/ext-apps`). That is what Claude, ChatGPT, Goose and
// VS Code speak, and what the bundled Chainlit host (public/elements/McpView.jsx)
// implements the other end of.
//
// The SDK handles the `ui/initialize` handshake, delivers the tool's result
// (`ui/notifications/tool-result`), and sends a chat message (`ui/message`).
// This module wraps it in two tiny functions so the views stay host-agnostic:
//
//   onData(handler)   — the tool's structuredContent, once the host sends it
//   sendMessage(text) — a user turn back into the chat, to run the next tool
import { App } from "@modelcontextprotocol/ext-apps";

// One App per iframe, connected once. Created lazily on first use so the
// tool-result handler is registered before connect() runs the handshake (the
// SDK warns if a handler is added after connect()).
let appPromise: Promise<App> | null = null;
let dataHandler: ((payload: unknown) => void) | null = null;

function app(): Promise<App> {
  if (!appPromise) {
    const instance = new App({ name: "stac-explorer-view", version: "0.1.0" });
    // The host delivers the tool's structuredContent here; hand it to whatever
    // onData registered. Read dataHandler lazily so a later onData still wins.
    instance.ontoolresult = (params) => {
      if (params.structuredContent != null) dataHandler?.(params.structuredContent);
    };
    appPromise = instance.connect().then(() => instance);
  }
  return appPromise;
}

/** Register for the tool's structuredContent, and connect to the host. */
export function onData<T>(handler: (payload: T) => void): void {
  dataHandler = handler as (payload: unknown) => void;
  void app();
}

/** Send text back into the conversation, so the model calls the next tool. */
export function sendMessage(text: string): void {
  void app().then((instance) =>
    instance.sendMessage({ role: "user", content: [{ type: "text", text }] }),
  );
}
