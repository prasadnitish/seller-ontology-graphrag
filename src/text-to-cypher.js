const WRITES=/\b(CREATE|MERGE|DELETE|DETACH|SET|DROP|REMOVE|CALL\s+dbms)\b/i;
export function assertReadOnlyTenantQuery(cypher) {
  if (WRITES.test(cypher)) throw new Error("Generated Cypher contains a prohibited write clause");
  if (/\[\s*\*\s*\]/.test(cypher)) throw new Error("Generated Cypher contains an unbounded traversal");
  if (!/tenant_id:\s*\$tenant_id/.test(cypher)) throw new Error("Generated Cypher is missing the tenant predicate");
  if (!/LIMIT\s+\d+/i.test(cypher)) throw new Error("Generated Cypher must include a result limit");
  return true;
}
export function generateCypher(question,{tenant_id}) {
  if (!tenant_id) throw new Error("Signed tenant context is required"); const q=question.toLowerCase(); let cypher, intent;
  if (/which sellers|eligible/.test(q)) { intent="seller_program_region"; cypher="MATCH (s:Seller {tenant_id: $tenant_id})-[:APPLIES_IN]->(r:Region {tenant_id: $tenant_id}), (s)-[:ELIGIBLE_FOR]->(p:Program {tenant_id: $tenant_id}) OPTIONAL MATCH (p)-[:CHARGES]->(f:Fee {tenant_id: $tenant_id}) RETURN s,r,p,f LIMIT 100"; }
  else if (/fee|charge/.test(q)) { intent="program_fee"; cypher="MATCH (p:Program {tenant_id: $tenant_id})-[:CHARGES]->(f:Fee {tenant_id: $tenant_id}) RETURN p,f LIMIT 100"; }
  else if (/policy|govern/.test(q)) { intent="program_policy"; cypher="MATCH (p:Program {tenant_id: $tenant_id})-[:GOVERNED_BY]->(x:Policy {tenant_id: $tenant_id}) RETURN p,x LIMIT 100"; }
  else if (/waiv/.test(q)) { intent="waiver"; cypher="MATCH (p:Program {tenant_id: $tenant_id})-[:GOVERNED_BY]->(x:Policy {tenant_id: $tenant_id})-[:WAIVED_BY]->(e:EligibilityRule {tenant_id: $tenant_id}) RETURN p,x,e LIMIT 100"; }
  else { intent="seller_region"; cypher="MATCH (s:Seller {tenant_id: $tenant_id})-[:APPLIES_IN]->(r:Region {tenant_id: $tenant_id}) RETURN s,r LIMIT 100"; }
  assertReadOnlyTenantQuery(cypher); return {cypher,params:{tenant_id},intent};
}
