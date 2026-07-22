import { StrictMode, useEffect, useRef, useState } from "react";
import { createRoot } from "react-dom/client";
import L from "leaflet";
import "leaflet/dist/leaflet.css";

import { onData } from "./host";
import type { Collection, ShowMapResult } from "./types";
import "./styles.css";

function MapView({ collection, tileUrl }: { collection: Collection; tileUrl?: string }) {
  const ref = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (!ref.current) return;
    const map = L.map(ref.current, { attributionControl: true });
    L.tileLayer("https://tile.openstreetmap.org/{z}/{x}/{y}.png", {
      maxZoom: 19,
      attribution: "© OpenStreetMap",
    }).addTo(map);

    // Overlay the actual data when show_map returned a georeferenced tile URL;
    // the tiles are transparent off-coverage, so they clip to the real
    // footprint. The blue box is the collection's declared extent. We never
    // paint the thumbnail onto the map — it is a sample preview, not tiles.
    if (tileUrl) {
      L.tileLayer(tileUrl, {
        opacity: 0.85,
        maxZoom: 18,
        attribution: "© Microsoft Planetary Computer",
      }).addTo(map);
    }
    if (collection.bbox) {
      const [w, s, e, n] = collection.bbox;
      const bounds = L.latLngBounds([s, w], [n, e]);
      L.rectangle(bounds, { color: "#2563eb", weight: 2, fill: false }).addTo(map);
      map.fitBounds(bounds.pad(0.2));
    } else {
      map.setView([20, 0], 2);
    }
    return () => void map.remove();
  }, [collection, tileUrl]);

  return (
    <>
      <div id="map" ref={ref} />
      <div className="map-caption">
        {collection.thumbnail && (
          <img className="preview" src={collection.thumbnail} alt="" />
        )}
        <div>
          <strong>{collection.title}</strong>
          <div className="id">{collection.id}</div>
          <div className="note">
            {tileUrl
              ? "Live data layer, clipped to the collection extent (blue box)."
              : "Blue box = data extent. Preview is illustrative."}
          </div>
        </div>
      </div>
    </>
  );
}

function App() {
  const [result, setResult] = useState<ShowMapResult | null>(null);
  useEffect(() => {
    onData<ShowMapResult>(setResult);
  }, []);
  if (!result?.collection) return <div className="empty">Loading map…</div>;
  return <MapView collection={result.collection} tileUrl={result.tile_url} />;
}

createRoot(document.getElementById("root")!).render(
  <StrictMode>
    <App />
  </StrictMode>,
);
