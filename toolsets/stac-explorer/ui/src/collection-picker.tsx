import { StrictMode, useEffect, useState } from "react";
import { createRoot } from "react-dom/client";

import { onData, sendMessage } from "./host";
import type { Collection, SearchCollectionsResult } from "./types";
import "./styles.css";

function Card({ collection }: { collection: Collection }) {
  const pick = () =>
    // The round-trip: picking advances the chat, so the model calls show_map.
    sendMessage(
      `Show the "${collection.title}" collection on the map (id: ${collection.id}).`,
    );
  return (
    <div className="card">
      {collection.thumbnail ? (
        <img className="thumb" src={collection.thumbnail} alt="" loading="lazy" />
      ) : (
        <div className="thumb-placeholder">no preview</div>
      )}
      <div className="body">
        <h3>{collection.title}</h3>
        <span className="id">{collection.id}</span>
        <p>{collection.description}</p>
        <button className="select" onClick={pick}>
          Show on map
        </button>
      </div>
    </div>
  );
}

function App() {
  const [collections, setCollections] = useState<Collection[] | null>(null);

  useEffect(() => {
    onData<SearchCollectionsResult>((data) => setCollections(data.collections ?? []));
  }, []);

  if (collections === null) return <div className="empty">Loading…</div>;
  if (collections.length === 0) return <div className="empty">No collections matched.</div>;
  return (
    <div className="grid">
      {collections.map((collection) => (
        <Card key={collection.id} collection={collection} />
      ))}
    </div>
  );
}

createRoot(document.getElementById("root")!).render(
  <StrictMode>
    <App />
  </StrictMode>,
);
