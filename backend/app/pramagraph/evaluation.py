import json
from eth_hash.auto import keccak
def canonical(v): return json.dumps(v,sort_keys=True,separators=(",",":"),ensure_ascii=False).encode()
def digest(v): return "0x"+keccak(canonical(v)).hex()
def classify(call, verified):
    raw=call.raw_response; result=raw.get("result"); warnings=raw.get("warnings",[]); codes=[]
    if call.status!="SUCCEEDED": return "REJECTED",["ACQUISITION_NOT_SUCCESSFUL"]
    if not raw: return "REJECTED",["MISSING_RAW_RESPONSE"]
    if result is None or result=={} or result=="": return "REJECTED",["EMPTY_RESULT"]
    if not verified: return "REJECTED",["PROVENANCE_FAILED"]
    return ("LIMITED",["UPSTREAM_WARNING"]) if warnings else ("ADMITTED",[])
def decide(state):
    return ("BLOCK",["REQUIRED_EVIDENCE_REJECTED"]) if state=="STRUCTURALLY_BLOCKED" else (("REVIEW",["EVIDENCE_LIMITED"]) if state=="STRUCTURALLY_LIMITED" else ("PERMIT",["ALL_REQUIRED_EVIDENCE_ADMITTED"]))
