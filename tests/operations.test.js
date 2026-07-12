import test from "node:test";
import assert from "node:assert/strict";
import { SubgraphCache, applyEventWithRetry } from "../src/operations.js";

test("subgraph cache isolates tenants and invalidates affected entities", () => {
  const cache = new SubgraphCache();
  cache.set({ tenant_id: "a", fingerprint: "q", ontology_version: "v1", data_version: "v1" }, { ids: ["seller-1"] });
  assert.equal(cache.get({ tenant_id: "b", fingerprint: "q", ontology_version: "v1", data_version: "v1" }), null);
  cache.invalidateEntity("seller-1");
  assert.equal(cache.get({ tenant_id: "a", fingerprint: "q", ontology_version: "v1", data_version: "v1" }), null);
});

test("event writes retry conflicts and dead-letter exhausted work", async () => {
  let calls = 0; const dlq = [];
  const ok = await applyEventWithRetry({ idempotency_key: "x" }, async () => { calls++; if (calls < 3) throw Object.assign(new Error("conflict"), { code: "CONFLICT" }); }, { max_attempts: 3, dlq, wait: async () => {} });
  assert.equal(ok.status, "applied"); assert.equal(calls, 3);
  const failed = await applyEventWithRetry({ idempotency_key: "y" }, async () => { throw Object.assign(new Error("conflict"), { code: "CONFLICT" }); }, { max_attempts: 2, dlq, wait: async () => {} });
  assert.equal(failed.status, "dead_lettered"); assert.equal(dlq.length, 1);
});
