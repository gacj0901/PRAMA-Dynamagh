/** Single-use operation client. Signer and private persistence stay outside the LLM. */
export type Policy = {network:string;asset:string;recipient:string;domainName:string;domainVersion:string;maxRequestAtomic:bigint;maxSessionAtomic:bigint};
type Json = Record<string, any>;
export class PramaClient {
  private used=false;
  constructor(private policy:Policy, private signer:(challenge:Json)=>Promise<string>,
    private checkpoint:(receipt:Json)=>Promise<void>,
    private endpoint='https://prama-dynamagh.up.railway.app/v1/public/ask', private http:typeof fetch=fetch) {
    if(new URL(endpoint).protocol!=='https:')throw Error('HTTPS required');
  }
  async request(requested_intent:string,query:string,polls=30,intervalMs=2000):Promise<Json> {
    if(this.used)throw Error('Single-use operation; no automatic repayment');this.used=true;
    const body=JSON.stringify({requested_intent,query});
    const headers={'Content-Type':'application/json','Idempotency-Key':crypto.randomUUID()};
    const initial=await this.http(this.endpoint,{method:'POST',headers,body,redirect:'error',signal:AbortSignal.timeout(30000)});
    if(initial.status!==402)throw Error('Expected 402; stopped without signing');
    const challenge=JSON.parse(atob(initial.headers.get('PAYMENT-REQUIRED')||''));
    if(challenge.x402Version!==2||challenge.accepts?.length!==1)throw Error('Unsupported challenge');
    const r=challenge.accepts[0],p=this.policy;
    if(typeof r.amount!=='string'||!/^\d+$/.test(r.amount))throw Error('Invalid amount');
    const amount=BigInt(r.amount);
    if(amount<=0n||amount>p.maxRequestAtomic||amount>p.maxSessionAtomic)throw Error('Payment ceiling exceeded');
    if(r.scheme!=='exact'||r.network!==p.network||r.asset?.toLowerCase()!==p.asset.toLowerCase()||r.payTo?.toLowerCase()!==p.recipient.toLowerCase()||r.extra?.name!==p.domainName||r.extra?.version!==p.domainVersion||challenge.resource?.url!==this.endpoint||(r.resource!==undefined&&r.resource!==this.endpoint))throw Error('Unapproved terms');
    const signature=await this.signer(structuredClone(challenge));
    await this.checkpoint({state:'PAYMENT_SUBMISSION_PENDING',idempotency_key:headers['Idempotency-Key']});
    const paid=await this.http(this.endpoint,{method:'POST',headers:{...headers,'PAYMENT-SIGNATURE':signature},body,redirect:'error',signal:AbortSignal.timeout(30000)});
    if(paid.status!==202)throw Error('Paid response failed or ambiguous: STOP, never repay');
    const accepted=await paid.json();await this.checkpoint(accepted);
    if(!/^[0-9a-f-]{36}$/i.test(accepted.mandate_id)||accepted.result_endpoint!==`${this.endpoint}/${accepted.mandate_id}/result`||!accepted.result_capability)throw Error('Invalid result route: STOP');
    for(let i=0;i<polls;i++){
      const response=await this.http(accepted.result_endpoint,{headers:{'X-PRAMA-Result-Capability':accepted.result_capability},redirect:'error',signal:AbortSignal.timeout(30000)});
      if(response.status!==200)throw Error('Result failed; retain checkpoint, never repay');
      const result=await response.json();const status=result.consumer_result?.status;
      if(status==='DELIVERED'||status==='NOT_AVAILABLE')return result;
      if(status!=='PENDING')throw Error('Unknown result state');
      await new Promise(resolve=>setTimeout(resolve,intervalMs));
    }
    throw Error('Polling limit; retain capability, never repay');
  }
}
