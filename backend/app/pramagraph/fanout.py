"""Declared extension of generic structural evaluation for explicit fan-out."""
VERSION = "pramagraph-structural-fanout-v0.1"


def structural_state(evidence, tasks):
    failed = [t for t in tasks if t.required and t.status=="FAILED"]
    if not evidence or any(e.admissibility=="REJECTED" for e in evidence): return "STRUCTURALLY_BLOCKED"
    if failed or any(e.admissibility=="LIMITED" for e in evidence): return "STRUCTURALLY_LIMITED"
    return "STRUCTURALLY_ADMISSIBLE"


def failures(tasks):
    return [{"acquisition_id":t.acquisition_id,"ordinal":t.ordinal,"status":t.status,"failure_code":t.failure_code} for t in sorted(tasks,key=lambda t:(t.ordinal,t.acquisition_id)) if t.status=="FAILED"]
