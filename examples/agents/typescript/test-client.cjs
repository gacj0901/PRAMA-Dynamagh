// Run after tsc: PRAMA_EXAMPLE_BUILD points to the compiled prama-client.js.
const {test}=require('node:test');const assert=require('node:assert/strict');
const {PramaClient}=require(process.env.PRAMA_EXAMPLE_BUILD);
const endpoint='https://prama-dynamagh.up.railway.app/v1/public/ask';
function fixture(change={},paidStatus=202){
  const calls=[],signed=[],saved=[];
  const requirements={scheme:'exact',network:'eip155:84532',asset:'asset',payTo:'recipient',amount:'10000',extra:{name:'USDC',version:'2'},...change};
  const http=async(url,options={})=>{
    calls.push({url,...options});
    if(!options.method)return new Response(JSON.stringify({consumer_result:{status:'DELIVERED',results:[{content:'answer'}]}}));
    if(options.headers['PAYMENT-SIGNATURE'])return new Response(JSON.stringify({mandate_id:'00000000-0000-0000-0000-000000000001',result_endpoint:endpoint+'/00000000-0000-0000-0000-000000000001/result',result_capability:'test-cap'}),{status:paidStatus});
    return new Response('',{status:402,headers:{'PAYMENT-REQUIRED':btoa(JSON.stringify({x402Version:2,resource:{url:endpoint},accepts:[requirements]}))}});
  };
  const client=new PramaClient({network:'eip155:84532',asset:'asset',recipient:'recipient',domainName:'USDC',domainVersion:'2',maxRequestAtomic:50000n,maxSessionAtomic:250000n},async c=>{signed.push(c);return 'test-signature'},async c=>{saved.push(c)},endpoint,http);
  return {client,calls,signed,saved};
}
test('one paid submission, exact body, private capability checkpoint',async()=>{
  const f=fixture();assert.equal((await f.client.request('WEB_SEARCH',' need ')).consumer_result.status,'DELIVERED');
  assert.equal(f.calls.length,3);assert.equal(f.signed.length,1);assert.equal(f.calls[0].body,f.calls[1].body);assert.equal(f.saved[1].result_capability,'test-cap');
  await assert.rejects(()=>f.client.request('WEB_SEARCH','second'));assert.equal(f.calls.length,3);
});
for(const change of [{amount:'50001'},{network:'eip155:8453'},{asset:'other'},{payTo:'other'},{extra:{}},{scheme:'other'}]){
  test('reject '+JSON.stringify(change),async()=>{const f=fixture(change);await assert.rejects(()=>f.client.request('WEB_SEARCH','need'));assert.equal(f.signed.length,0);assert.equal(f.calls.length,1);});
}
test('ambiguous paid response never retries',async()=>{const f=fixture({},503);await assert.rejects(()=>f.client.request('WEB_SEARCH','need'));assert.equal(f.calls.length,2);assert.equal(f.signed.length,1);});
