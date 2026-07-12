import test from "node:test";
import assert from "node:assert/strict";
import source from "../datasets/seller-source.json" with { type: "json" };
import { answerQuestion } from "../src/graphrag.js";

test("answers multi-hop questions with citations and a trace", async () => {
  const result = await answerQuestion("Which US sellers are eligible for Growth and what fee applies?", { tenant_id: "demo", source });
  assert.match(result.answer, /Northstar/);
  assert.match(result.answer, /2.5%/);
  assert.ok(result.citations.length >= 2);
  assert.match(result.trace.cypher, /MATCH/);
});

test("returns insufficient data instead of hallucinating", async () => {
  const result = await answerQuestion("Which sellers operate on Mars?", { tenant_id: "demo", source });
  assert.equal(result.answer, "Insufficient data in the governed seller graph.");
});
