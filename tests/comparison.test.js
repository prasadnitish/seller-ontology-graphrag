import test from "node:test";import assert from "node:assert/strict";import {compareRuns} from "../eval/graphrag-vs-vectorrag.js";
test("comparison reports per-question winner and score delta",()=>{const [row]=compareRuns([{id:"x",graph_score:90,vector_score:70}]);assert.equal(row.winner,"GraphRAG");assert.equal(row.delta,20);});
