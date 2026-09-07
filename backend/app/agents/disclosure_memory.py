"""Versioned, event-sourced cumulative K-Mem dimension; G13 advisory only."""
from datetime import datetime, timezone, timedelta

from app.tickets.disclosure import VERSION, checked_core, events_for_agent, iso
from app.pramagraph.evaluation import digest


def replay_disclosure(events, *, as_of):
    """A fixed event stream + explicit cutoff always reconstruct the same result."""
    cutoff = as_of.replace(tzinfo=as_of.tzinfo or timezone.utc)
    rows = sorted((checked_core(item) for item in events), key=lambda item: (item["occurred_at"], item["event_id"]))
    rows = [item for item in rows if datetime.fromisoformat(item["occurred_at"]) <= cutoff]
    grouped = {}
    for item in rows:
        if item["response_hash"]:
            grouped.setdefault(item["response_hash"], []).append(item)
    counts = dict(eligible=0, evaluated_eligible=0, compliant=0, presented=0, hash_preserved=0, url_preserved=0,
                  missing=0, late=0, awaiting_presentation=0, hash_mismatch=0, url_mismatch=0)
    unique = {name: set() for name in ("ISSUED", "DELIVERED_TO_AGENT", "PRESENTED_BY_AGENT", "OPENED_BY_TITULAR", "VERIFIED_BY_TITULAR", "ACKNOWLEDGED_BY_TITULAR")}
    latencies = []
    for response_hash, history in sorted(grouped.items()):
        for name in unique:
            if any(e["event_type"] == "TITULAR_CHECK_" + name for e in history): unique[name].add(response_hash)
        deliveries = [e for e in history if e["event_type"] == "TITULAR_CHECK_DELIVERED_TO_AGENT"]
        anomalies = [e for e in history if e["event_type"] == "TITULAR_CHECK_PRESENTATION_INVALID"]
        counts["hash_mismatch"] += int(any(e["metadata"].get("reason") == "RESPONSE_HASH_MISMATCH" for e in anomalies))
        counts["url_mismatch"] += int(any(e["metadata"].get("reason") == "URL_MISMATCH" for e in anomalies))
        if not deliveries: continue
        counts["eligible"] += 1
        first = deliveries[0]
        start = datetime.fromisoformat(first["occurred_at"])
        deadline = start + timedelta(seconds=first["metadata"]["deadline_seconds"])
        presentations = [e for e in history if e["event_type"] == "TITULAR_CHECK_PRESENTED_BY_AGENT" and datetime.fromisoformat(e["occurred_at"]) >= start]
        presentation = presentations[0] if presentations else None
        # Grace period avoids penalizing a request while it is still in flight.
        if not presentation and cutoff < deadline:
            counts["awaiting_presentation"] += 1
            continue
        counts["evaluated_eligible"] += 1
        if not presentation:
            counts["missing"] += 1
            continue
        counts["presented"] += 1
        latency = int((datetime.fromisoformat(presentation["occurred_at"]) - start).total_seconds() * 1000)
        latencies.append({"response_hash": response_hash, "latency_ms": latency})
        hash_ok = presentation["metadata"].get("response_hash_preserved") is True
        url_ok = presentation["metadata"].get("url") == first["metadata"]["url"]
        on_time = datetime.fromisoformat(presentation["occurred_at"]) <= deadline
        counts["hash_preserved"] += int(hash_ok)
        counts["url_preserved"] += int(url_ok)
        counts["late"] += int(not on_time)
        counts["compliant"] += int(hash_ok and url_ok and on_time)
    result = {
        "version": VERSION, "as_of": iso(cutoff), **counts,
        "compliance": counts["compliant"] / counts["evaluated_eligible"] if counts["evaluated_eligible"] else None,
        "titular_checks_issued": len(unique["ISSUED"]),
        "titular_checks_delivered": len(unique["DELIVERED_TO_AGENT"]),
        "titular_checks_presented": len(unique["PRESENTED_BY_AGENT"]),
        "presentation_missing_count": counts["missing"], "presentation_latency_ms": latencies,
        "response_hash_preserved_count": counts["hash_preserved"],
        "response_hash_mismatch_count": counts["hash_mismatch"],
        "titular_checks_opened": len(unique["OPENED_BY_TITULAR"]),
        "titular_checks_verified": len(unique["VERIFIED_BY_TITULAR"]),
        "titular_checks_acknowledged": len(unique["ACKNOWLEDGED_BY_TITULAR"]),
        "source_event_ids": [e["event_id"] for e in rows],
        "g13_signal": "AVAILABLE_POLICY_SIGNAL", "enforcement": "UNCHANGED",
        "memory_kind": "CUMULATIVE_EVENT_REPLAY", "principal_events_affect_score": False,
    }
    return {**result, "projection_hash": digest(result)}


def build_disclosure_memory(session, identity_id, *, as_of):
    return replay_disclosure(events_for_agent(session, identity_id), as_of=as_of)
