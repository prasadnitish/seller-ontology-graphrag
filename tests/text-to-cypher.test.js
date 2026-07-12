import test from "node:test";
import assert from "node:assert/strict";
import { generateCypher, assertReadOnlyTenantQuery } from "../src/text-to-cypher.js";

test("generates bounded tenant-scoped read queries for supported intents", () => {
  for (const q of ["Which sellers in US are eligible for Growth?", "What fee does Growth charge?", "Which policy governs Growth?", "Which waiver applies to Growth?", "Where does Northstar sell?"]) {
    const result = generateCypher(q, { tenant_id: "demo" });
    assert.match(result.cypher, /tenant_id: \$tenant_id/);
    assert.match(result.cypher, /LIMIT 100/);
    assert.doesNotThrow(() => assertReadOnlyTenantQuery(result.cypher));
  }
});

test("rejects writes, unbounded traversal, and missing tenant predicates", () => {
  assert.throws(() => assertReadOnlyTenantQuery("MATCH (n) DELETE n"), /write/);
  assert.throws(() => assertReadOnlyTenantQuery("MATCH (n)-[*]->(m) RETURN m"), /unbounded/);
  assert.throws(() => assertReadOnlyTenantQuery("MATCH (n) RETURN n LIMIT 10"), /tenant/);
});
