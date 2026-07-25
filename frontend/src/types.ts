export type PropertySpec = {
  type: "string" | "integer" | "number" | "boolean" | "date" | "datetime";
  required: boolean;
  description: string;
};

export type Source = {
  id: string;
  path: string;
  format: "csv" | "json" | "markdown" | "text";
  record_path?: string;
  ignored_fields: Record<string, string>;
};

export type GraphSpec = {
  metadata: {
    name: string;
    version: string;
    tenant_id: string;
    description: string;
  };
  sources: Source[];
  node_types: Array<{
    name: string;
    key: string;
    description: string;
    properties: Record<string, PropertySpec>;
  }>;
  relationship_types: Array<{
    name: string;
    from_type: string;
    to_type: string;
    description: string;
    properties: Record<string, PropertySpec>;
  }>;
  node_mappings: Array<{
    id: string;
    source: string;
    node_type: string;
    key_field: string;
    properties: Record<string, string>;
  }>;
  relationship_mappings: Array<{
    id: string;
    source: string;
    relationship_type: string;
    from_field: string;
    to_field: string;
    properties: Record<string, string>;
  }>;
  query_recipes: Array<{
    id: string;
    description: string;
    route: "graph" | "vector" | "hybrid";
    examples: string[];
    parameters: Record<string, unknown>;
    cypher?: string;
    result_description: string;
  }>;
  vector: { enabled: boolean; chunk_size: number; chunk_overlap: number; top_k: number };
  ui: { nodes: Record<string, { x: number; y: number }> };
};

export type Workspace = {
  profile: {
    sources: Array<{
      id: string;
      relative_path: string;
      format: string;
      sha256: string;
      size_bytes: number;
      record_count: number | null;
      fields: Array<{
        name: string;
        inferred_type: string;
        sensitive: boolean;
        samples: unknown[];
      }>;
      warnings: string[];
    }>;
  };
  spec: GraphSpec;
  validation: {
    valid: boolean;
    mapped_fields: number;
    ignored_fields: number;
    unmapped_fields: number;
    issues: Array<{ severity: string; code: string; message: string; location: string }>;
  };
  approval: { approved_at: string; spec_hash: string; source_manifest_hash: string } | null;
  approval_current: boolean;
};
