"""Capability-scoped projection of admitted evidence, never provider transport."""
import os
import re


DELIVERY_EVENT = "M2M_CONSUMER_RESULT_DELIVERED"
_PRIVATE_KEY = re.compile(
    r"privatekey|seedphrase|mnemonic|signature|capability|authorization|bearer|"
    r"apikey|cookie|credential|password|secret|accesstoken|refreshtoken|"
    r"headers|rawresponse|rawpayload|transport|privatemetadata|internalmetadata|"
    r"databaseurl|connectionstring|^token$|^seed$"
)
_BEARER = re.compile(r"(?i)\bBearer\s+[A-Za-z0-9._~+/=-]+")
_DATABASE = re.compile(r"(?i)(?:postgres(?:ql)?|mysql|redis)(?:\+\w+)?://[^\s]+")
_ASSIGNMENT = re.compile(
    r"(?i)\b(?:api[_-]?key|private[_-]?key|payment[_-]?signature|result[_-]?capability|"
    r"access[_-]?token|password|secret|authorization|cookie)\s*[=:]\s*[^\s&,;]+"
)
_PEM = re.compile(r"-----BEGIN [^-]*PRIVATE KEY-----.*?-----END [^-]*PRIVATE KEY-----", re.S)
_URL_CREDENTIALS = re.compile(r"(?i)(https?://)[^/\s@]+@")


def sanitize(value, secrets=()):
    """Remove private fields recursively; preserve ordinary JSON intelligence."""
    if isinstance(value, dict):
        return {key: sanitize(item, secrets) for key, item in value.items()
                if not _PRIVATE_KEY.search(re.sub(r"[^a-z0-9]", "", key.lower()))}
    if isinstance(value, list):
        return [sanitize(item, secrets) for item in value]
    if isinstance(value, str):
        for secret in secrets:
            if secret:
                value = value.replace(secret, "[REDACTED]")
        for pattern in (_PEM, _DATABASE, _BEARER, _ASSIGNMENT):
            value = pattern.sub("[REDACTED]", value)
        return _URL_CREDENTIALS.sub(r"\1[REDACTED]@", value)
    return value


def has_content(value):
    if isinstance(value, dict):
        return any(has_content(item) for item in value.values())
    if isinstance(value, list):
        return any(has_content(item) for item in value)
    if isinstance(value, str):
        return bool(value.replace("[REDACTED]", "").strip())
    return value is not None  # Zero and false are legitimate intelligence.


def project_consumer_result(mandate, tasks, evidence, secrets=()):
    known_secrets = tuple(secrets) + tuple(
        value for key, value in os.environ.items()
        if len(value) >= 8 and _PRIVATE_KEY.search(re.sub(r"[^a-z0-9]", "", key.lower()))
    )
    by_id = {task.acquisition_id: task for task in tasks
             if task.mandate_id == mandate.mandate_id}
    results = []
    for item in evidence:
        task = by_id.get(item.acquisition_id)
        if (item.mandate_id != mandate.mandate_id or task is None
                or item.admissibility != "ADMITTED" or item.provenance_status != "VERIFIED"
                or not isinstance(item.normalized_payload, dict)):
            continue
        content = sanitize(item.normalized_payload.get("result"), known_secrets)
        if has_content(content):
            results.append({
                "acquisition_id": task.acquisition_id,
                "requested_intent": task.requested_intent,
                "evidence_id": item.evidence_id,
                "evidence_content_hash": item.content_hash,
                "content": content,
            })
    status = "DELIVERED" if results else (
        "NOT_AVAILABLE" if mandate.status in {"TICKETED", "FAILED"} else "PENDING"
    )
    return {"status": status, "results": results}
