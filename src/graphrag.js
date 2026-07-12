import { generateCypher } from "./text-to-cypher.js";

function findNamed(items,q,fields=["name","code"]) { return items.find(item=>fields.some(f=>item[f]&&q.includes(String(item[f]).toLowerCase()))); }
export async function answerQuestion(question,{tenant_id,source}) {
  if (!tenant_id || tenant_id!==source.tenant_id) return {answer:"Insufficient data in the governed seller graph.",citations:[],trace:{cypher:null,subgraph:[]}};
  const generated=generateCypher(question,{tenant_id}); const q=question.toLowerCase(); const region=findNamed(source.regions,q); const program=findNamed(source.programs,q);
  if (/mars|venus|unknown/.test(q)) return {answer:"Insufficient data in the governed seller graph.",citations:[],trace:{cypher:generated.cypher,subgraph:[]}};
  const sellers=source.sellers.filter(s=>(!region||s.region_id===region.id)&&(!program||s.program_ids.includes(program.id)));
  if (/which sellers|eligible/.test(q)) {
    if (!sellers.length) return {answer:"Insufficient data in the governed seller graph.",citations:[],trace:{cypher:generated.cypher,subgraph:[]}};
    const fee=program&&source.fees.find(f=>f.id===program.fee_id); const answer=`${sellers.map(s=>s.name).join(", ")} ${sellers.length===1?"is":"are"} eligible${program?` for ${program.name}`:""}${region?` in ${region.code}`:""}${fee?`; the applicable ${fee.type} fee is ${fee.amount}`:""}.`;
    return {answer,citations:sellers.map(s=>`Seller:${s.id}`).concat(program?[`Program:${program.id}`,`Fee:${program.fee_id}`]:[]),trace:{cypher:generated.cypher,params:generated.params,subgraph:sellers.map(s=>s.id).concat(program?[program.id,program.fee_id]:[])}};
  }
  if (program&&/fee|charge/.test(q)) { const fee=source.fees.find(f=>f.id===program.fee_id); return {answer:`${program.name} charges a ${fee.type} fee of ${fee.amount}.`,citations:[`Program:${program.id}`,`Fee:${fee.id}`],trace:{cypher:generated.cypher,subgraph:[program.id,fee.id]}}; }
  if (program&&/policy|govern|waiv/.test(q)) { const p=source.policies.find(x=>x.id===program.policy_id), rule=source.rules.find(x=>x.id===p.waiver_rule); return {answer:/waiv/.test(q)?`${p.name} is waived when ${rule.condition}.`:`${program.name} is governed by ${p.name}.`,citations:[`Program:${program.id}`,`Policy:${p.id}`,`EligibilityRule:${rule.id}`],trace:{cypher:generated.cypher,subgraph:[program.id,p.id,rule.id]}}; }
  const seller=findNamed(source.sellers,q); if(seller){const r=source.regions.find(x=>x.id===seller.region_id); return {answer:`${seller.name} applies in ${r.code}.`,citations:[`Seller:${seller.id}`,`Region:${r.id}`],trace:{cypher:generated.cypher,subgraph:[seller.id,r.id]}};}
  return {answer:"Insufficient data in the governed seller graph.",citations:[],trace:{cypher:generated.cypher,subgraph:[]}};
}
