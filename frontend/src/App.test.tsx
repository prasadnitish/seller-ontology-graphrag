import { render, screen } from "@testing-library/react";
import { beforeEach, expect, test, vi } from "vitest";
import App from "./App";

const workspace = {
  profile: { sources: [] },
  spec: {
    metadata: { name: "Test Graph", version: "1", tenant_id: "demo", description: "Test" },
    sources: [],
    node_types: [{ name: "Service", key: "id", description: "", properties: { id: { type: "string", required: true, description: "" } } }],
    relationship_types: [],
    node_mappings: [],
    relationship_mappings: [],
    query_recipes: [],
    vector: { enabled: true, chunk_size: 900, chunk_overlap: 100, top_k: 5 },
    ui: { nodes: {} },
  },
  validation: { valid: true, mapped_fields: 0, ignored_fields: 0, unmapped_fields: 0, issues: [] },
  approval: null,
  approval_current: false,
};

beforeEach(() => {
  vi.stubGlobal("fetch", vi.fn(async () => new Response(JSON.stringify(workspace), {
    status: 200,
    headers: { "Content-Type": "application/json" },
  })));
  class ResizeObserverMock {
    observe() {}
    unobserve() {}
    disconnect() {}
  }
  vi.stubGlobal("ResizeObserver", ResizeObserverMock);
});

test("shows approval state and all semantic work areas", async () => {
  render(<App />);
  expect(await screen.findByText("Test Graph")).toBeInTheDocument();
  expect(screen.getByText("DRAFT")).toBeInTheDocument();
  expect(screen.getByRole("button", { name: "Mappings" })).toBeInTheDocument();
  expect(screen.getByRole("button", { name: "Query Recipes" })).toBeInTheDocument();
  expect(screen.getByRole("button", { name: "Validation" })).toBeInTheDocument();
});
