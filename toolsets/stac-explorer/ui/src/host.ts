// The host bridge — the one seam a view shares no matter what framework it is
// built with. A view runs in a sandboxed iframe and talks to its host (Claude
// web, an mcp-ui client, or the bundled Chainlit agent) over postMessage:
//
//   iframe -> host  { type: "mcp:ready" }            when it is ready for data
//   host   -> iframe { type: "mcp:data", payload }   the tool's structuredContent
//   iframe -> host  { type: "mcp:sendMessage", text } to advance the chat
//
// Keeping this tiny and explicit means a host only has to speak three messages,
// and a view never reaches for credentials or the network beyond what the tool
// put in `payload`.

type DataHandler<T> = (payload: T) => void;

/** Register for the tool's structuredContent, and announce readiness. */
export function onData<T>(handler: DataHandler<T>): void {
  window.addEventListener("message", (event: MessageEvent) => {
    const message = event.data;
    if (message && message.type === "mcp:data") {
      handler(message.payload as T);
    }
  });
  window.parent.postMessage({ type: "mcp:ready" }, "*");
}

/** Send text back into the conversation, so the model calls the next tool. */
export function sendMessage(text: string): void {
  window.parent.postMessage({ type: "mcp:sendMessage", text }, "*");
}
