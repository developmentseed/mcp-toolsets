// Shapes mirror the toolset's ToolResult subclasses (stac_explorer/tools.py).
// The host injects the whole structuredContent as the view's `mcp:data` payload.

export interface Collection {
  id: string;
  title: string;
  description: string;
  thumbnail?: string;
  bbox?: [number, number, number, number];
}

export interface SearchCollectionsResult {
  message: string;
  collections?: Collection[];
}

export interface ShowMapResult {
  message: string;
  collection?: Collection;
  tile_url?: string;
}
