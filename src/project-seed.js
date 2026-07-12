import { readFile, writeFile, mkdir } from "node:fs/promises";
import { pathToFileURL } from "node:url";

export function projectSeed(source) {
  const tenant = source.tenant_id;
  const nodes = [];
  for (const [label, items] of [["Seller",source.sellers],["Program",source.programs],["Policy",source.policies],["Region",source.regions],["Fee",source.fees],["EligibilityRule",source.rules]]) {
    for (const item of items) nodes.push({ label, ...item, tenant_id: tenant });
  }
  const relationships = []; const facts = [];
  const by = (items,id) => items.find(x=>x.id===id);
  for (const seller of source.sellers) {
    const region=by(source.regions,seller.region_id);
    relationships.push({ from:seller.id,type:"APPLIES_IN",to:region.id,tenant_id:tenant });
    facts.push(`${seller.name} applies in ${region.code}.`);
    for (const id of seller.program_ids) { const p=by(source.programs,id); relationships.push({from:seller.id,type:"ELIGIBLE_FOR",to:id,tenant_id:tenant}); facts.push(`${seller.name} is eligible for ${p.name}.`); }
  }
  for (const p of source.programs) {
    const policy=by(source.policies,p.policy_id), fee=by(source.fees,p.fee_id);
    relationships.push({from:p.id,type:"GOVERNED_BY",to:policy.id,tenant_id:tenant},{from:p.id,type:"CHARGES",to:fee.id,tenant_id:tenant});
    facts.push(`${p.name} is governed by ${policy.name}.`,`${p.name} charges a ${fee.type} fee of ${fee.amount}.`);
  }
  for (const policy of source.policies) { const rule=by(source.rules,policy.waiver_rule); relationships.push({from:policy.id,type:"WAIVED_BY",to:rule.id,tenant_id:tenant}); facts.push(`${policy.name} is waived when ${rule.condition}.`); }
  return { graph:{nodes,relationships,fact_sentences:facts,counts:{sellers:source.sellers.length,programs:source.programs.length,policies:source.policies.length,regions:source.regions.length,fees:source.fees.length,rules:source.rules.length,relationships:relationships.length}}, corpus:`# Synthetic seller policy corpus\n\n${facts.join("\n")}` };
}

if (import.meta.url === pathToFileURL(process.argv[1] ?? "").href) {
  const source=JSON.parse(await readFile(new URL("../datasets/seller-source.json",import.meta.url),"utf8"));
  const {graph,corpus}=projectSeed(source); await mkdir(new URL("../generated/",import.meta.url),{recursive:true});
  await writeFile(new URL("../generated/seller-graph-seed.json",import.meta.url),`${JSON.stringify(graph,null,2)}\n`);
  await writeFile(new URL("../generated/seller-corpus.md",import.meta.url),`${corpus}\n`);
}
