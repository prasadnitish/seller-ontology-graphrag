import test from "node:test";
import assert from "node:assert/strict";
import source from "../datasets/seller-source.json" with { type: "json" };
import { projectSeed } from "../src/project-seed.js";

test("graph and prose are lossless projections of one source", () => {
  const { graph, corpus } = projectSeed(source);
  assert.deepEqual(graph.counts, { sellers: 12, programs: 4, policies: 6, regions: 5, fees: 4, rules: 6, relationships: 55 });
  for (const fact of graph.fact_sentences) assert.ok(corpus.includes(fact), fact);
});
