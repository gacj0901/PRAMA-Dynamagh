const labels = {external_m2m_requests:'External M2M Requests',settled_m2m_requests:'Settled M2M Requests',unique_paying_wallets:'Unique Paying Wallets',declared_client_labels:'Declared Client Labels',registered_m2m_agent_identities:'Registered M2M Agent Identities',successful_acquisitions:'Successful Acquisitions',admitted_evidence:'Admitted Evidence',consumer_fulfilled:'Consumer Fulfilled'};
const nodes = {};
for (const [key,label] of Object.entries(labels)) {
  const box=document.createElement('div'); box.className='metric';
  const name=document.createElement('span');name.className='label';name.textContent=label;
  const value=document.createElement('strong');value.className='value';value.textContent='UNKNOWN';
  box.append(name,value);document.getElementById('metrics').append(box);nodes[key]=value;
}
fetch('/v1/public/adoption',{credentials:'omit'}).then(r=>{if(!r.ok)throw Error('unavailable');return r.json();}).then(data=>{
  for(const [key,node] of Object.entries(nodes))node.textContent=Number.isSafeInteger(data.metrics[key])?String(data.metrics[key]):'UNKNOWN';
  document.getElementById('observed').textContent='OBSERVED '+data.observed_at+' · persisted records · refresh page to update';
  const proof=data.verified_execution;
  document.getElementById('proof-source').textContent=proof.verification+' — '+proof.source;
  for(const [key,label] of Object.entries({client:'Declared client',intent:'Intent',payment_usdc:'Payment (USDC)',acquisition:'Acquisition',evidence:'Evidence',provenance:'Provenance',decision:'Decision',consumer_result:'Consumer Result'})){
    const dt=document.createElement('dt');dt.textContent=label;const dd=document.createElement('dd');dd.textContent=proof[key]||'UNKNOWN';document.getElementById('proof').append(dt,dd);
  }
  document.getElementById('proof-hash').textContent=proof.evidence_content_hash;
  document.getElementById('bazaar').textContent=data.bazaar_metadata_declared?'DECLARED':'UNKNOWN';
}).catch(()=>{document.getElementById('observed').textContent='Metrics unavailable — UNKNOWN; no estimated values.';document.getElementById('proof-source').textContent='Proof verification unavailable.';});
