const LABELS=new Set(["Seller","Program","Policy","Region","Fee","EligibilityRule"]);
const RELS=new Set(["ELIGIBLE_FOR","GOVERNED_BY","APPLIES_IN","CHARGES","WAIVED_BY"]);
export async function ingestGraph(session,graph,{batch_size=500}={}) {
  for(let i=0;i<graph.nodes.length;i+=batch_size){const batch=graph.nodes.slice(i,i+batch_size); for(const label of LABELS){const rows=batch.filter(n=>n.label===label).map(({label:_,...n})=>n);if(rows.length)await session.run(`UNWIND $rows AS row MERGE (n:${label} {tenant_id: row.tenant_id, id: row.id}) SET n += row`,{rows});}}
  for(let i=0;i<graph.relationships.length;i+=batch_size){const batch=graph.relationships.slice(i,i+batch_size);for(const type of RELS){const rows=batch.filter(r=>r.type===type);if(rows.length)await session.run(`UNWIND $rows AS row MATCH (a {tenant_id: row.tenant_id, id: row.from}), (b {tenant_id: row.tenant_id, id: row.to}) MERGE (a)-[:${type}]->(b)`,{rows});}}
  return graph.counts;
}
