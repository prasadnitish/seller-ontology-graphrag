import { useCallback, useEffect, useMemo, useState } from "react";
import {
  Background,
  Controls,
  Edge,
  MarkerType,
  Node,
  ReactFlow,
  applyNodeChanges,
  type NodeChange,
} from "@xyflow/react";
import type { GraphSpec, Workspace } from "./types";

type Tab = "Sources" | "Ontology" | "Mappings" | "Query Recipes" | "Validation";
const tabs: Tab[] = ["Sources", "Ontology", "Mappings", "Query Recipes", "Validation"];
const csrfToken =
  document.querySelector<HTMLMetaElement>('meta[name="graphkit-token"]')?.content ?? "";

async function request<T>(url: string, init: RequestInit = {}): Promise<T> {
  const response = await fetch(url, {
    ...init,
    credentials: "same-origin",
    headers: {
      "Content-Type": "application/json",
      ...(init.method && init.method !== "GET" ? { "X-GraphKit-Token": csrfToken } : {}),
      ...init.headers,
    },
  });
  if (!response.ok) {
    const body = await response.text();
    throw new Error(`${response.status}: ${body}`);
  }
  return response.json() as Promise<T>;
}

function graphElements(spec: GraphSpec): { nodes: Node[]; edges: Edge[] } {
  const nodes = spec.node_types.map((item, index) => ({
    id: item.name,
    position: spec.ui.nodes[item.name] ?? {
      x: 50 + (index % 3) * 260,
      y: 60 + Math.floor(index / 3) * 170,
    },
    data: {
      label: (
        <div className="graph-node">
          <span className="eyebrow">ENTITY</span>
          <strong>{item.name}</strong>
          <span>{Object.keys(item.properties).length} properties · key {item.key}</span>
        </div>
      ),
    },
    className: "ontology-node",
  }));
  const edges = spec.relationship_types.map((item) => ({
    id: `${item.from_type}-${item.name}-${item.to_type}`,
    source: item.from_type,
    target: item.to_type,
    label: item.name,
    markerEnd: { type: MarkerType.ArrowClosed },
    className: "ontology-edge",
  }));
  return { nodes, edges };
}

export default function App() {
  const [workspace, setWorkspace] = useState<Workspace | null>(null);
  const [spec, setSpec] = useState<GraphSpec | null>(null);
  const [tab, setTab] = useState<Tab>("Sources");
  const [notice, setNotice] = useState("Loading workspace…");
  const [busy, setBusy] = useState(false);

  const refresh = useCallback(async () => {
    try {
      const next = await request<Workspace>("/api/workspace");
      setWorkspace(next);
      setSpec(next.spec);
      setNotice(next.approval_current ? "Approved and current" : "Draft requires approval");
    } catch (error) {
      setNotice(error instanceof Error ? error.message : "Unable to load workspace");
    }
  }, []);

  useEffect(() => {
    void refresh();
  }, [refresh]);

  const elements = useMemo(() => (spec ? graphElements(spec) : { nodes: [], edges: [] }), [spec]);
  const [flowNodes, setFlowNodes] = useState<Node[]>([]);
  useEffect(() => setFlowNodes(elements.nodes), [elements.nodes]);

  const onNodesChange = useCallback(
    (changes: NodeChange[]) => {
      setFlowNodes((current) => {
        const next = applyNodeChanges(changes, current);
        if (changes.some((change) => change.type === "position")) {
          setSpec((currentSpec) => {
            if (!currentSpec) return currentSpec;
            const positions = Object.fromEntries(next.map((node) => [node.id, node.position]));
            return { ...currentSpec, ui: { nodes: positions } };
          });
        }
        return next;
      });
    },
    [],
  );

  const save = async () => {
    if (!spec) return;
    setBusy(true);
    try {
      await request("/api/workspace/spec", { method: "PUT", body: JSON.stringify(spec) });
      await refresh();
      setNotice("Draft saved atomically");
    } catch (error) {
      setNotice(error instanceof Error ? error.message : "Save failed");
    } finally {
      setBusy(false);
    }
  };

  const action = async (name: "validate" | "approve" | "build" | "evaluate") => {
    setBusy(true);
    try {
      if (spec) {
        await request("/api/workspace/spec", { method: "PUT", body: JSON.stringify(spec) });
      }
      await request(`/api/workspace/${name}`, { method: "POST" });
      await refresh();
      setNotice(
        name === "approve"
          ? "GraphSpec and source manifest approved"
          : `${name[0].toUpperCase()}${name.slice(1)} completed`,
      );
      if (name === "validate") setTab("Validation");
    } catch (error) {
      setNotice(error instanceof Error ? error.message : `${name} failed`);
    } finally {
      setBusy(false);
    }
  };

  if (!workspace || !spec) {
    return (
      <main className="loading-shell">
        <p className="eyebrow">GRAPHKIT / LOCAL</p>
        <h1>Opening the ontology workbench</h1>
        <p>{notice}</p>
      </main>
    );
  }

  return (
    <main>
      <header className="masthead">
        <div>
          <p className="eyebrow">GRAPHKIT / ONTOLOGY CONTROL PLANE</p>
          <h1>{spec.metadata.name}</h1>
          <p className="lede">{spec.metadata.description}</p>
        </div>
        <div className="status-stack" aria-live="polite">
          <span className={workspace.approval_current ? "status approved" : "status draft"}>
            {workspace.approval_current ? "APPROVED" : "DRAFT"}
          </span>
          <span>{notice}</span>
          <span>v{spec.metadata.version} · tenant {spec.metadata.tenant_id}</span>
        </div>
      </header>

      <section className="command-bar" aria-label="Workbench actions">
        <button onClick={save} disabled={busy}>Save draft</button>
        <button onClick={() => action("validate")} disabled={busy}>Validate</button>
        <button onClick={() => action("approve")} disabled={busy} className="primary">Approve</button>
        <button onClick={() => action("build")} disabled={busy || !workspace.approval_current}>Build</button>
        <button onClick={() => action("evaluate")} disabled={busy || !workspace.approval_current}>Evaluate</button>
      </section>

      <section className="workbench-grid">
        <div className="semantic-panel">
          <nav className="tabs" aria-label="GraphSpec work areas">
            {tabs.map((item) => (
              <button
                key={item}
                aria-current={tab === item ? "page" : undefined}
                onClick={() => setTab(item)}
              >
                {item}
              </button>
            ))}
          </nav>
          <div className="panel-body">
            {tab === "Sources" && <Sources workspace={workspace} />}
            {tab === "Ontology" && <Ontology spec={spec} setSpec={setSpec} />}
            {tab === "Mappings" && <Mappings spec={spec} workspace={workspace} setSpec={setSpec} />}
            {tab === "Query Recipes" && <Recipes spec={spec} setSpec={setSpec} />}
            {tab === "Validation" && <Validation workspace={workspace} />}
          </div>
        </div>

        <aside className="canvas-panel">
          <div className="section-heading">
            <div>
              <p className="eyebrow">LIVE STRUCTURE</p>
              <h2>Ontology map</h2>
            </div>
            <span>Drag changes layout only</span>
          </div>
          <div className="canvas">
            <ReactFlow
              key={flowNodes.length}
              nodes={flowNodes}
              edges={elements.edges}
              onNodesChange={onNodesChange}
              fitView
              minZoom={0.35}
              maxZoom={1.5}
              nodesConnectable={false}
              elementsSelectable
            >
              <Background gap={22} size={1} />
              <Controls showInteractive={false} />
            </ReactFlow>
          </div>
          <EvidenceRail workspace={workspace} spec={spec} />
        </aside>
      </section>
    </main>
  );
}

function Sources({ workspace }: { workspace: Workspace }) {
  return (
    <div className="stack">
      <div className="section-heading">
        <div><p className="eyebrow">01 / INPUTS</p><h2>Source manifest</h2></div>
        <span>{workspace.profile.sources.length} files</span>
      </div>
      {workspace.profile.sources.map((source) => (
        <article className="data-card" key={source.relative_path}>
          <div className="card-title">
            <div><strong>{source.relative_path}</strong><span>{source.format}</span></div>
            <code>{source.sha256.slice(0, 10)}</code>
          </div>
          <p>{source.record_count ?? "—"} records · {source.size_bytes.toLocaleString()} bytes</p>
          {source.fields.length > 0 && (
            <div className="field-list">
              {source.fields.map((field) => (
                <span className={field.sensitive ? "field sensitive" : "field"} key={field.name}>
                  {field.name} <em>{field.inferred_type}</em>
                </span>
              ))}
            </div>
          )}
          {source.warnings.map((warning) => <p className="warning" key={warning}>{warning}</p>)}
        </article>
      ))}
    </div>
  );
}

function Ontology({
  spec,
  setSpec,
}: {
  spec: GraphSpec;
  setSpec: (spec: GraphSpec) => void;
}) {
  const updateNode = (index: number, patch: Partial<GraphSpec["node_types"][number]>) => {
    const items = [...spec.node_types];
    items[index] = { ...items[index], ...patch };
    setSpec({ ...spec, node_types: items });
  };
  const removeNode = (index: number) => {
    if (!confirm("Delete this node type? Related mappings and relationships must be resolved.")) return;
    setSpec({ ...spec, node_types: spec.node_types.filter((_, item) => item !== index) });
  };
  const addNode = () => {
    const name = `NewEntity${spec.node_types.length + 1}`;
    setSpec({
      ...spec,
      node_types: [
        ...spec.node_types,
        {
          name,
          key: "id",
          description: "",
          properties: { id: { type: "string", required: true, description: "" } },
        },
      ],
      ui: { nodes: { ...spec.ui.nodes, [name]: { x: 120, y: 120 } } },
    });
  };
  return (
    <div className="stack">
      <div className="section-heading">
        <div><p className="eyebrow">02 / SEMANTICS</p><h2>Node types</h2></div>
        <button onClick={addNode}>+ Add node</button>
      </div>
      {spec.node_types.map((node, index) => (
        <article className="editor-card" key={`${node.name}-${index}`}>
          <label>Name<input value={node.name} onChange={(event) => updateNode(index, { name: event.target.value })} /></label>
          <label>Key property<input value={node.key} onChange={(event) => updateNode(index, { key: event.target.value })} /></label>
          <label className="wide">Description<textarea value={node.description} onChange={(event) => updateNode(index, { description: event.target.value })} /></label>
          <PropertiesEditor
            properties={node.properties}
            onChange={(properties) => updateNode(index, { properties })}
          />
          <button className="danger" onClick={() => removeNode(index)}>Delete node type</button>
        </article>
      ))}
      <div className="section-heading">
        <div><p className="eyebrow">03 / EDGES</p><h2>Relationships</h2></div>
        <button onClick={() => {
          if (spec.node_types.length === 0) return;
          const from = spec.node_types[0].name;
          const to = spec.node_types[Math.min(1, spec.node_types.length - 1)].name;
          setSpec({
            ...spec,
            relationship_types: [
              ...spec.relationship_types,
              {
                name: `RELATES_TO_${spec.relationship_types.length + 1}`,
                from_type: from,
                to_type: to,
                description: "",
                properties: {},
              },
            ],
          });
        }}>+ Add relationship</button>
      </div>
      {spec.relationship_types.map((relationship, index) => (
        <article className="editor-card" key={`${relationship.name}-${index}`}>
          <label>Name<input value={relationship.name} onChange={(event) => {
            const items = [...spec.relationship_types];
            items[index] = { ...relationship, name: event.target.value };
            setSpec({ ...spec, relationship_types: items });
          }} /></label>
          <label>From<select value={relationship.from_type} onChange={(event) => {
            const items = [...spec.relationship_types];
            items[index] = { ...relationship, from_type: event.target.value };
            setSpec({ ...spec, relationship_types: items });
          }}>{spec.node_types.map((node) => <option key={node.name}>{node.name}</option>)}</select></label>
          <label>To<select value={relationship.to_type} onChange={(event) => {
            const items = [...spec.relationship_types];
            items[index] = { ...relationship, to_type: event.target.value };
            setSpec({ ...spec, relationship_types: items });
          }}>{spec.node_types.map((node) => <option key={node.name}>{node.name}</option>)}</select></label>
          <button className="danger" onClick={() => {
            if (!confirm("Delete this relationship type? Related mappings must be resolved.")) return;
            setSpec({
              ...spec,
              relationship_types: spec.relationship_types.filter((_, item) => item !== index),
            });
          }}>Delete relationship type</button>
        </article>
      ))}
    </div>
  );
}

function Mappings({
  spec,
  workspace,
  setSpec,
}: {
  spec: GraphSpec;
  workspace: Workspace;
  setSpec: (spec: GraphSpec) => void;
}) {
  const mapped = useMemo(() => {
    const values = new Set<string>();
    spec.node_mappings.forEach((mapping) => {
      values.add(`${mapping.source}:${mapping.key_field}`);
      Object.values(mapping.properties).forEach((field) => values.add(`${mapping.source}:${field}`));
    });
    spec.relationship_mappings.forEach((mapping) => {
      values.add(`${mapping.source}:${mapping.from_field}`);
      values.add(`${mapping.source}:${mapping.to_field}`);
      Object.values(mapping.properties).forEach((field) => values.add(`${mapping.source}:${field}`));
    });
    return values;
  }, [spec]);
  return (
    <div className="stack">
      <div className="section-heading">
        <div><p className="eyebrow">04 / COVERAGE</p><h2>Structured fields</h2></div>
        <span>{workspace.validation.unmapped_fields} unresolved</span>
      </div>
      {workspace.profile.sources.filter((source) => source.fields.length > 0).map((source) => (
        <article className="data-card" key={source.id}>
          <strong>{source.relative_path}</strong>
          <div className="mapping-list">
            {source.fields.map((field) => {
              const ignored = spec.sources.find((item) => item.id === source.id)?.ignored_fields[field.name];
              const state = mapped.has(`${source.id}:${field.name}`) ? "mapped" : ignored ? "ignored" : "unresolved";
              return (
                <div key={field.name}>
                  <span>{field.name}</span><span className={`coverage ${state}`}>{state}</span>
                  {state !== "mapped" && (
                    <input
                      aria-label={`Ignore reason for ${field.name}`}
                      placeholder="Reason to ignore"
                      value={ignored ?? ""}
                      onChange={(event) => {
                        const sources = spec.sources.map((item) =>
                          item.id === source.id
                            ? {
                                ...item,
                                ignored_fields: {
                                  ...item.ignored_fields,
                                  ...(event.target.value
                                    ? { [field.name]: event.target.value }
                                    : {}),
                                },
                              }
                            : item,
                        );
                        if (!event.target.value) delete sources.find((item) => item.id === source.id)!.ignored_fields[field.name];
                        setSpec({ ...spec, sources });
                      }}
                    />
                  )}
                </div>
              );
            })}
          </div>
        </article>
      ))}
      <div className="section-heading"><div><p className="eyebrow">MAPPING RULES</p><h2>Compiler mappings</h2></div></div>
      <div className="section-heading compact">
        <strong>Node mappings</strong>
        <button onClick={() => {
          const source = spec.sources.find((item) => item.format === "csv" || item.format === "json");
          const node = spec.node_types[0];
          if (!source || !node) return;
          setSpec({
            ...spec,
            node_mappings: [...spec.node_mappings, {
              id: `node_mapping_${spec.node_mappings.length + 1}`,
              source: source.id,
              node_type: node.name,
              key_field: "id",
              properties: {},
            }],
          });
        }}>+ Add mapping</button>
      </div>
      {spec.node_mappings.map((mapping, index) => (
        <article className="editor-card" key={`${mapping.id}-${index}`}>
          <label>ID<input value={mapping.id} onChange={(event) => {
            const items = [...spec.node_mappings];
            items[index] = { ...mapping, id: event.target.value };
            setSpec({ ...spec, node_mappings: items });
          }} /></label>
          <label>Source<select value={mapping.source} onChange={(event) => {
            const items = [...spec.node_mappings];
            items[index] = { ...mapping, source: event.target.value };
            setSpec({ ...spec, node_mappings: items });
          }}>{spec.sources.filter((item) => item.format === "csv" || item.format === "json").map((item) => <option key={item.id}>{item.id}</option>)}</select></label>
          <label>Node type<select value={mapping.node_type} onChange={(event) => {
            const items = [...spec.node_mappings];
            items[index] = { ...mapping, node_type: event.target.value };
            setSpec({ ...spec, node_mappings: items });
          }}>{spec.node_types.map((item) => <option key={item.name}>{item.name}</option>)}</select></label>
          <label>Key field<input value={mapping.key_field} onChange={(event) => {
            const items = [...spec.node_mappings];
            items[index] = { ...mapping, key_field: event.target.value };
            setSpec({ ...spec, node_mappings: items });
          }} /></label>
          <JsonRecordEditor
            label="Property mapping JSON"
            value={mapping.properties}
            onChange={(properties) => {
              const items = [...spec.node_mappings];
              items[index] = { ...mapping, properties };
              setSpec({ ...spec, node_mappings: items });
            }}
          />
          <button className="danger" onClick={() => {
            if (!confirm("Delete this node mapping?")) return;
            setSpec({ ...spec, node_mappings: spec.node_mappings.filter((_, item) => item !== index) });
          }}>Delete mapping</button>
        </article>
      ))}
      <div className="section-heading compact">
        <strong>Relationship mappings</strong>
        <button onClick={() => {
          const source = spec.sources.find((item) => item.format === "csv" || item.format === "json");
          const relationship = spec.relationship_types[0];
          if (!source || !relationship) return;
          setSpec({
            ...spec,
            relationship_mappings: [...spec.relationship_mappings, {
              id: `relationship_mapping_${spec.relationship_mappings.length + 1}`,
              source: source.id,
              relationship_type: relationship.name,
              from_field: "from_id",
              to_field: "to_id",
              properties: {},
            }],
          });
        }}>+ Add mapping</button>
      </div>
      {spec.relationship_mappings.map((mapping, index) => (
        <article className="editor-card" key={`${mapping.id}-${index}`}>
          <label>ID<input value={mapping.id} onChange={(event) => {
            const items = [...spec.relationship_mappings];
            items[index] = { ...mapping, id: event.target.value };
            setSpec({ ...spec, relationship_mappings: items });
          }} /></label>
          <label>Source<select value={mapping.source} onChange={(event) => {
            const items = [...spec.relationship_mappings];
            items[index] = { ...mapping, source: event.target.value };
            setSpec({ ...spec, relationship_mappings: items });
          }}>{spec.sources.filter((item) => item.format === "csv" || item.format === "json").map((item) => <option key={item.id}>{item.id}</option>)}</select></label>
          <label>Relationship<select value={mapping.relationship_type} onChange={(event) => {
            const items = [...spec.relationship_mappings];
            items[index] = { ...mapping, relationship_type: event.target.value };
            setSpec({ ...spec, relationship_mappings: items });
          }}>{spec.relationship_types.map((item) => <option key={item.name}>{item.name}</option>)}</select></label>
          <label>From field<input value={mapping.from_field} onChange={(event) => {
            const items = [...spec.relationship_mappings];
            items[index] = { ...mapping, from_field: event.target.value };
            setSpec({ ...spec, relationship_mappings: items });
          }} /></label>
          <label>To field<input value={mapping.to_field} onChange={(event) => {
            const items = [...spec.relationship_mappings];
            items[index] = { ...mapping, to_field: event.target.value };
            setSpec({ ...spec, relationship_mappings: items });
          }} /></label>
          <JsonRecordEditor
            label="Property mapping JSON"
            value={mapping.properties}
            onChange={(properties) => {
              const items = [...spec.relationship_mappings];
              items[index] = { ...mapping, properties };
              setSpec({ ...spec, relationship_mappings: items });
            }}
          />
          <button className="danger" onClick={() => {
            if (!confirm("Delete this relationship mapping?")) return;
            setSpec({ ...spec, relationship_mappings: spec.relationship_mappings.filter((_, item) => item !== index) });
          }}>Delete mapping</button>
        </article>
      ))}
    </div>
  );
}

function Recipes({ spec, setSpec }: { spec: GraphSpec; setSpec: (spec: GraphSpec) => void }) {
  const update = (index: number, patch: Partial<GraphSpec["query_recipes"][number]>) => {
    const items = [...spec.query_recipes];
    items[index] = { ...items[index], ...patch };
    setSpec({ ...spec, query_recipes: items });
  };
  return (
    <div className="stack">
      <div className="section-heading">
        <div><p className="eyebrow">05 / SAFE QUERYING</p><h2>Approved recipes</h2></div>
        <button onClick={() => setSpec({
          ...spec,
          query_recipes: [...spec.query_recipes, {
            id: `new_recipe_${spec.query_recipes.length + 1}`,
            description: "",
            route: "vector",
            examples: ["Replace with a representative question"],
            parameters: {},
            result_description: "",
          }],
        })}>+ Add recipe</button>
      </div>
      {spec.query_recipes.map((recipe, index) => (
        <article className="recipe-card" key={recipe.id}>
          <div className="route-line"><code>{recipe.id}</code><span className={`route ${recipe.route}`}>{recipe.route}</span></div>
          <label>Description<textarea value={recipe.description} onChange={(event) => update(index, { description: event.target.value })} /></label>
          <label>Route<select value={recipe.route} onChange={(event) => update(index, { route: event.target.value as "graph" | "vector" | "hybrid" })}>
            <option value="graph">graph</option><option value="vector">vector</option><option value="hybrid">hybrid</option>
          </select></label>
          <label>Example questions<textarea value={recipe.examples.join("\n")} onChange={(event) => update(index, { examples: event.target.value.split("\n").filter(Boolean) })} /></label>
          {recipe.route !== "vector" && <label>Read-only Cypher<textarea className="code-area" value={recipe.cypher ?? ""} onChange={(event) => update(index, { cypher: event.target.value })} /></label>}
          <button className="danger" onClick={() => {
            if (!confirm("Delete this query recipe?")) return;
            setSpec({ ...spec, query_recipes: spec.query_recipes.filter((_, item) => item !== index) });
          }}>Delete recipe</button>
        </article>
      ))}
    </div>
  );
}

function Validation({ workspace }: { workspace: Workspace }) {
  const report = workspace.validation;
  return (
    <div className="stack">
      <div className="validation-hero">
        <span className={report.valid ? "validation-mark valid" : "validation-mark invalid"}>
          {report.valid ? "PASS" : "FAIL"}
        </span>
        <div><p className="eyebrow">VALIDATION GATE</p><h2>{report.valid ? "Ready for approval" : "Resolve blocking issues"}</h2></div>
      </div>
      <div className="metric-grid">
        <Metric value={report.mapped_fields} label="mapped fields" />
        <Metric value={report.ignored_fields} label="ignored with reason" />
        <Metric value={report.unmapped_fields} label="unresolved" />
      </div>
      {report.issues.length === 0 ? <p className="empty">No validation issues.</p> : report.issues.map((issue) => (
        <article className={`issue ${issue.severity}`} key={`${issue.code}-${issue.location}`}>
          <code>{issue.code}</code><strong>{issue.message}</strong><span>{issue.location}</span>
        </article>
      ))}
    </div>
  );
}

function EvidenceRail({ workspace, spec }: { workspace: Workspace; spec: GraphSpec }) {
  return (
    <div className="evidence-rail">
      <p className="eyebrow">EVIDENCE CHAIN</p>
      <ol>
        <li><span>Sources</span><strong>{workspace.profile.sources.length} hashed</strong></li>
        <li><span>Coverage</span><strong>{workspace.validation.unmapped_fields === 0 ? "complete" : "blocked"}</strong></li>
        <li><span>Recipes</span><strong>{spec.query_recipes.length} bounded</strong></li>
        <li><span>Approval</span><strong>{workspace.approval_current ? "current" : "required"}</strong></li>
      </ol>
    </div>
  );
}

function Metric({ value, label }: { value: number; label: string }) {
  return <div className="metric"><strong>{value}</strong><span>{label}</span></div>;
}

function PropertiesEditor({
  properties,
  onChange,
}: {
  properties: GraphSpec["node_types"][number]["properties"];
  onChange: (properties: GraphSpec["node_types"][number]["properties"]) => void;
}) {
  const entries = Object.entries(properties);
  return (
    <div className="wide property-editor">
      <div className="route-line"><span>Properties</span><button onClick={() => {
        let name = `property_${entries.length + 1}`;
        while (properties[name]) name = `${name}_new`;
        onChange({ ...properties, [name]: { type: "string", required: false, description: "" } });
      }}>+ Add property</button></div>
      {entries.map(([name, property], index) => (
        <div className="property-edit-row" key={`${name}-${index}`}>
          <input aria-label="Property name" value={name} onChange={(event) => {
            const next = Object.fromEntries(entries.map(([currentName, current], item) => (
              item === index ? [event.target.value, current] : [currentName, current]
            )));
            onChange(next);
          }} />
          <select aria-label={`Type for ${name}`} value={property.type} onChange={(event) => {
            onChange({ ...properties, [name]: { ...property, type: event.target.value as typeof property.type } });
          }}>
            {["string", "integer", "number", "boolean", "date", "datetime"].map((type) => <option key={type}>{type}</option>)}
          </select>
          <label className="check"><input type="checkbox" checked={property.required} onChange={(event) => {
            onChange({ ...properties, [name]: { ...property, required: event.target.checked } });
          }} /> required</label>
          <button aria-label={`Delete ${name}`} onClick={() => onChange(Object.fromEntries(entries.filter((_, item) => item !== index)))}>×</button>
        </div>
      ))}
    </div>
  );
}

function JsonRecordEditor({
  label,
  value,
  onChange,
}: {
  label: string;
  value: Record<string, string>;
  onChange: (value: Record<string, string>) => void;
}) {
  const [draft, setDraft] = useState(JSON.stringify(value, null, 2));
  const [error, setError] = useState("");
  useEffect(() => setDraft(JSON.stringify(value, null, 2)), [value]);
  return (
    <label className="wide">
      {label}
      <textarea
        className="json-area"
        value={draft}
        aria-invalid={Boolean(error)}
        onChange={(event) => {
          setDraft(event.target.value);
          try {
            const parsed = JSON.parse(event.target.value);
            if (!parsed || Array.isArray(parsed) || typeof parsed !== "object") throw new Error();
            if (!Object.values(parsed).every((item) => typeof item === "string")) throw new Error();
            setError("");
            onChange(parsed as Record<string, string>);
          } catch {
            setError("Use a JSON object with string field names and string values.");
          }
        }}
      />
      {error && <span className="inline-error">{error}</span>}
    </label>
  );
}
