// Renders a toolset's UI view in a sandboxed iframe and implements the *host*
// end of the MCP Apps `ui/*` JSON-RPC-over-postMessage bridge (the same protocol
// Claude, ChatGPT, Goose and VS Code speak; the view's end is the standard
// @modelcontextprotocol/ext-apps SDK — see toolsets/*/ui/src/host.ts).
//
//   view "ui/initialize" (request)        -> we reply with host info + context
//   view "ui/notifications/initialized"   -> we push tool-input then tool-result
//   view "ui/message" (request)           -> sendUserMessage(), then reply {}
//   view "ui/notifications/size-changed"  -> ignored (the panel frame is fixed)
//
// Props (from web.py): { html: the ui:// resource bundle, data: structuredContent }.
// The bundle is rendered via srcdoc, so the frame has an opaque origin and needs
// only allow-scripts — never allow-same-origin.
import { useEffect, useRef } from "react";

const PROTOCOL_VERSION = "2026-01-26"; // ext-apps LATEST_PROTOCOL_VERSION

export default function McpView() {
  const ref = useRef(null);
  const { html, data } = props;
  // Each turn mounts a fresh element, so data is stable per instance; hold it in
  // a ref so the mount-once listener always sends the current value.
  const dataRef = useRef(data);
  dataRef.current = data;

  useEffect(() => {
    const iframe = ref.current;
    if (!iframe) return;
    const post = (message) => iframe.contentWindow?.postMessage(message, "*");

    function onMessage(event) {
      if (event.source !== iframe.contentWindow) return;
      const message = event.data;
      if (!message || message.jsonrpc !== "2.0") return;

      if (message.method === "ui/initialize") {
        post({
          jsonrpc: "2.0",
          id: message.id,
          result: {
            protocolVersion: PROTOCOL_VERSION,
            hostInfo: { name: "chainlit-mcpview", version: "1.0.0" },
            hostCapabilities: { message: { text: {} } },
            hostContext: {},
          },
        });
      } else if (message.method === "ui/notifications/initialized") {
        // tool-input MUST precede tool-result per the spec; the view only needs
        // the result, and we don't track the call's arguments here, so send an
        // empty set to satisfy the ordering.
        post({
          jsonrpc: "2.0",
          method: "ui/notifications/tool-input",
          params: { arguments: {} },
        });
        post({
          jsonrpc: "2.0",
          method: "ui/notifications/tool-result",
          params: { content: [], structuredContent: dataRef.current },
        });
      } else if (message.method === "ui/message" && message.id !== undefined) {
        // content is a ContentBlock[]; join the text blocks into the user turn.
        const text = (message.params?.content ?? [])
          .filter((block) => block?.type === "text" && typeof block.text === "string")
          .map((block) => block.text)
          .join("");
        if (text) sendUserMessage(text);
        post({ jsonrpc: "2.0", id: message.id, result: {} });
      }
    }

    window.addEventListener("message", onMessage);
    return () => window.removeEventListener("message", onMessage);
  }, []);

  return (
    <iframe
      ref={ref}
      srcDoc={html}
      sandbox="allow-scripts"
      style={{
        width: "100%",
        height: "100%",
        border: "1px solid var(--border, #e4e7ec)",
        borderRadius: 10,
      }}
    />
  );
}
