// Renders a toolset's UI view in a sandboxed iframe and bridges the postMessage
// protocol (see toolsets/*/ui/src/host.ts) into Chainlit:
//
//   iframe "mcp:ready"        -> we post the tool's structuredContent down
//   iframe "mcp:sendMessage"  -> sendUserMessage(), so the agent runs the next tool
//
// Props (from web.py): { html: the ui:// resource bundle, data: structuredContent }.
// The bundle is rendered via srcdoc, so the frame has an opaque origin and needs
// only allow-scripts — never allow-same-origin.
import { useEffect, useRef } from "react";

export default function McpView() {
  const ref = useRef(null);
  const { html, data } = props;

  const postData = () =>
    ref.current?.contentWindow?.postMessage({ type: "mcp:data", payload: data }, "*");

  useEffect(() => {
    function onMessage(event) {
      const message = event.data;
      if (!message || event.source !== ref.current?.contentWindow) return;
      if (message.type === "mcp:ready") {
        postData();
      } else if (message.type === "mcp:sendMessage" && typeof message.text === "string") {
        sendUserMessage(message.text);
      }
    }
    window.addEventListener("message", onMessage);
    return () => window.removeEventListener("message", onMessage);
  }, []);

  return (
    <iframe
      ref={ref}
      srcDoc={html}
      onLoad={postData}
      sandbox="allow-scripts"
      style={{
        width: "100%",
        height: 440,
        border: "1px solid var(--border, #e4e7ec)",
        borderRadius: 10,
      }}
    />
  );
}
